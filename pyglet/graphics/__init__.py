# $Id:$

'''Low-level graphics rendering.

This module provides an efficient low-level abstraction over OpenGL.  It gives
very good performance for rendering OpenGL primitives; far better than the
typical immediate-mode usage and, on modern graphics cards, better than using
display lists in many cases.  The module is used internally by other areas of
pyglet.  

See the `pyglet Programming Guide <http://www.pyglet.org/doc>`_ for details on
how to use this graphics API.

Data item parameters
====================

Many of the functions and methods in this module accept any number of ``data``
parameters as their final parameters.  In the documentation these are notated
as ``*data`` in the formal parameter list.

A data parameter describes a vertex attribute format and an optional sequence
to initialise that attribute.  Examples of common attribute formats are:

``"v3f"``
    Vertex position, specified as three floats.
``"c4B"``
    Vertex color, specifed as four unsigned bytes.
``"t2f"``
    Texture coordinate, specified as two floats.

See `pyglet.graphics.vertexattribute` for the complete syntax of the vertex
format string.

When no initial data is to be given, the data item is just the format string.
For example, the following creates a 4 element vertex list with position and
color attributes::

    vertex_list = pyglet.graphics.vertex_list(4, 'v2f', 'c4B')

When initial data is required, wrap the format string and the initial data in
a tuple, for example::

    vertex_list = pyglet.graphics.vertex_list(4, 
                                              ('v2f', (0.0, 1.0, 1.0, 0.0)),
                                              ('c4B', (255, 255, 255, 255)))

Drawing modes
=============

Methods in this module that accept a ``mode`` parameter will accept any value
in the OpenGL drawing mode enumeration; for example, ``GL_POINTS``,
``GL_LINES``, ``GL_TRIANGLES``, etc.  

Because of the way the graphics API renders multiple primitives with shared
state, ``GL_POLYGON``, ``GL_LINE_LOOP`` and ``GL_TRIANGLE_FAN`` cannot be used
--- the results are undefined.

When using ``GL_LINE_STRIP``, ``GL_TRIANGLE_STRIP`` or ``GL_QUAD_STRIP`` care
must be taken to insert degenrate vertices at the beginning and end of each
vertex list.  For example, given the vertex list::

    A, B, C, D

the correct vertex list to provide the vertex list is::

    A, A, B, C, D, D

Alternatively, the ``NV_primitive_restart`` extension can be used if it is
present.  This also permits use of ``GL_POLYGON``, ``GL_LINE_LOOP`` and
``GL_TRIANGLE_FAN``.   Unfortunatley the extension is not provided by older
video drivers, and requires indexed vertex lists.

:since: pyglet 1.1
'''

import ctypes

import pyglet
from pyglet.gl import *
from pyglet.graphics import vertexbuffer, vertexattribute, vertexdomain

_debug_graphics_batch = pyglet.options['debug_graphics_batch']

def draw(size, mode, *data):
    '''Draw a primitive immediately.

    :Parameters:
        `size` : int
            Number of vertices given
        `mode` : int
            OpenGL drawing mode, e.g. ``GL_TRIANGLES``
        `data` : data items
            Attribute formats and data.  See the module summary for 
            details.

    '''
    glPushClientAttrib(GL_CLIENT_VERTEX_ARRAY_BIT)

    for format, array in data:
        attribute = vertexattribute.create_attribute(format)
        assert size == len(array) // attribute.count, \
            'Data for %s is incorrect length' % format
        buffer = vertexbuffer.create_mappable_buffer(
            size * attribute.stride, vbo=False)

        attribute.set_region(buffer, 0, size, array)
        attribute.enable()
        attribute.set_pointer(buffer.ptr)

    glDrawArrays(mode, 0, size)
        
    glPopClientAttrib()

def draw_indexed(size, mode, indices, *data):
    '''Draw a primitive with indexed vertices immediately.

    :Parameters:
        `size` : int
            Number of vertices given
        `mode` : int
            OpenGL drawing mode, e.g. ``GL_TRIANGLES``
        `indices` : sequence of int
            Sequence of integers giving indices into the vertex list.
        `data` : data items
            Attribute formats and data.  See the module summary for details.

    '''
    glPushClientAttrib(GL_CLIENT_VERTEX_ARRAY_BIT)

    for format, array in data:
        attribute = vertexattribute.create_attribute(format)
        assert size == len(array) // attribute.count, \
            'Data for %s is incorrect length' % format
        buffer = vertexbuffer.create_mappable_buffer(
            size * attribute.stride, vbo=False)

        attribute.set_region(buffer, 0, size, array)
        attribute.enable()
        attribute.set_pointer(buffer.ptr)

    if size <= 0xff:
        index_type = GL_UNSIGNED_BYTE
        index_c_type = ctypes.c_ubyte
    elif size <= 0xffff:
        index_type = GL_UNSIGNED_SHORT
        index_c_type = ctypes.c_ushort
    else:
        index_type = GL_UNSIGNED_INT
        index_c_type = ctypes.c_uint

    index_array = (index_c_type * len(indices))(*indices)
    glDrawElements(mode, len(indices), index_type, index_array)
    
    glPopClientAttrib()

def _parse_data(data):
    '''Given a list of data items, returns (formats, initial_arrays).'''
    assert data, 'No attribute formats given'

    # Return tuple (formats, initial_arrays).
    formats = []
    initial_arrays = []
    for i, format in enumerate(data):
        if isinstance(format, tuple):
            format, array = format
            initial_arrays.append((i, array))
        formats.append(format)
    formats = tuple(formats)
    return formats, initial_arrays

def _get_default_batch():
    shared_object_space = get_current_context().object_space
    try:
        return shared_object_space.pyglet_graphics_default_batch
    except AttributeError:
        shared_object_space.pyglet_graphics_default_batch = Batch()
        return shared_object_space.pyglet_graphics_default_batch

def vertex_list(count, *data):
    '''Create a `VertexList` not associated with a batch, group or mode.

    :Parameters:
        `count` : int
            The number of vertices in the list.
        `data` : data items
            Attribute formats and initial data for the vertex list.  See the
            module summary for details.

    :rtype: `VertexList`
    '''
    # Note that mode=0 because the default batch is never drawn: vertex lists
    # returned from this function are drawn directly by the app.
    return _get_default_batch().add(count, 0, None, *data)

def vertex_list_indexed(count, indices, *data):
    '''Create an `IndexedVertexList` not associated with a batch, group or mode.

    :Parameters:
        `count` : int
            The number of vertices in the list.
        `indices` : sequence
            Sequence of integers giving indices into the vertex list.
        `data` : data items
            Attribute formats and initial data for the vertex list.  See the
            module summary for details.

    :rtype: `IndexedVertexList`
    '''
    # Note that mode=0 because the default batch is never drawn: vertex lists
    # returned from this function are drawn directly by the app.
    return _get_default_batch().add_indexed(count, 0, None, indices, *data)

class Batch(object):
    '''Manage a collection of vertex lists for batched rendering.

    Vertex lists are added to a `Batch` using the `add` and `add_indexed`
    methods.  An optional group can be specified along with the vertex list,
    which gives the OpenGL state required for its rendering.  Vertex lists
    with shared mode and group are allocated into adjacent areas of memory and
    sent to the graphics card in a single operation.

    Call `VertexList.delete` to remove a vertex list from the batch.
    '''
    def __init__(self):
        '''Create a graphics batch.'''
        # Mapping to find domain.  
        # group -> (attributes, mode, indexed) -> domain
        self.group_map = {}

        # Mapping of group to list of children.
        self.group_children = {}

        # List of top-level groups
        self.top_groups = []

        self._draw_list = []
        self._draw_list_dirty = False

    def add(self, count, mode, group, *data):
        '''Add a vertex list to the batch.

        :Parameters:
            `count` : int
                The number of vertices in the list.
            `mode` : int
                OpenGL drawing mode enumeration; for example, one of
                ``GL_POINTS``, ``GL_LINES``, ``GL_TRIANGLES``, etc.
                See the module summary for additional information.
            `group` : `AbstractGroup`
                Group of the vertex list, or ``None`` if no group is required.
            `data` : data items
                Attribute formats and initial data for the vertex list.  See
                the module summary for details.

        :rtype: `VertexList`
        '''
        formats, initial_arrays = _parse_data(data)
        domain = self._get_domain(False, mode, group, formats)
        domain.__formats = formats
            
        # Create vertex list and initialize
        vlist = domain.create(count)
        for i, array in initial_arrays:
            vlist._set_attribute_data(i, array)

        return vlist

    def add_indexed(self, count, mode, group, indices, *data):
        '''Add an indexed vertex list to the batch.

        :Parameters:
            `count` : int
                The number of vertices in the list.
            `mode` : int
                OpenGL drawing mode enumeration; for example, one of
                ``GL_POINTS``, ``GL_LINES``, ``GL_TRIANGLES``, etc.
                See the module summary for additional information.
            `group` : `AbstractGroup`
                Group of the vertex list, or ``None`` if no group is required.
            `indices` : sequence
                Sequence of integers giving indices into the vertex list.
            `data` : data items
                Attribute formats and initial data for the vertex list.  See
                the module summary for details.

        :rtype: `IndexedVertexList`
        '''
        formats, initial_arrays = _parse_data(data)
        domain = self._get_domain(True, mode, group, formats)
            
        # Create vertex list and initialize
        vlist = domain.create(count, len(indices))
        start = vlist.start
        vlist._set_index_data(map(lambda i: i + start, indices))
        for i, array in initial_arrays:
            vlist._set_attribute_data(i, array)

        return vlist 

    def migrate(self, vertex_list, mode, group, batch):
        '''Migrate a vertex list to another batch and/or group.

        `vertex_list` and `mode` together identify the vertex list to migrate.
        `group` and `batch` are new owners of the vertex list after migration.  

        The results are undefined if `mode` is not correct or if `vertex_list`
        does not belong to this batch (they are not checked and will not
        necessarily throw an exception immediately).

        `batch` can remain unchanged if only a group change is desired.
        
        :Parameters:
            `vertex_list` : `VertexList`
                A vertex list currently belonging to this batch.
            `mode` : int
                The current GL drawing mode of the vertex list.
            `group` : `Group`
                The new group to migrate to.
            `batch` : `Batch`
                The batch to migrate to (or the current batch).

        '''
        formats = vertex_list.domain.__formats
        domain = batch._get_domain(False, mode, group, formats)
        vertex_list.migrate(domain)

    def _get_domain(self, indexed, mode, group, formats):
        if group is None:
            group = null_group
        
        # Batch group
        if group not in self.group_map:
            self._add_group(group)

        domain_map = self.group_map[group]

        # Find domain given formats, indices and mode
        key = (formats, mode, indexed)
        try:
            domain = domain_map[key]
        except KeyError:
            # Create domain
            if indexed:
                domain = vertexdomain.create_indexed_domain(*formats)
            else:
                domain = vertexdomain.create_domain(*formats)
            domain_map[key] = domain
            self._draw_list_dirty = True 

        return domain

    def _add_group(self, group):
        self.group_map[group] = {}
        if group.parent is None:
            self.top_groups.append(group)
        else:
            if group.parent not in self.group_map:
                self._add_group(group.parent)
            if group.parent not in self.group_children:
                self.group_children[group.parent] = []
            self.group_children[group.parent].append(group)
        self._draw_list_dirty = True

    def _update_draw_list(self):
        # Visit group tree in preorder and create a list of bound methods
        # to call.
        draw_list = []

        def visit(group):
            draw_list.append(group.set_state)

            # Draw domains using this group
            domain_map = self.group_map[group]
            for (_, mode, _), domain in domain_map.items():
                draw_list.append(
                    (lambda d, m: lambda: d.draw(m))(domain, mode))

            # Sort and visit child groups of this group
            children = self.group_children.get(group)
            if children:
                children.sort()
                for child in children:
                    visit(child)

            draw_list.append(group.unset_state)

        self.top_groups.sort()
        for group in self.top_groups:
            visit(group)

        self._draw_list = draw_list
        self._draw_list_dirty = False

        if _debug_graphics_batch:
            self._dump_draw_list()

    def _dump_draw_list(self):
        def dump(group, indent=''):
            print indent, 'Begin group', group
            domain_map = self.group_map[group]
            for _, domain in domain_map.items():
                print indent, '  ', domain
            for child in self.group_children.get(group, ()):
                dump(child, indent + '  ')
            print indent, 'End group', group

        print 'Draw list for %r:' % self
        for group in self.top_groups:
            dump(group)
        
    def draw(self):
        '''Draw the batch.
        '''
        if self._draw_list_dirty:
            self._update_draw_list()

        for func in self._draw_list:
            func()

    def draw_subset(self, vertex_lists):
        '''Draw only some vertex lists in the batch.

        The use of this method is highly discouraged, as it is quite
        inefficient.  Usually an application can be redesigned so that batches
        can always be drawn in their entirety, using `draw`.

        The given vertex lists must belong to this batch; behaviour is
        undefined if this condition is not met.

        :Parameters:
            `vertex_lists` : sequence of `VertexList` or `IndexedVertexList`
                Vertex lists to draw.

        '''
        # Horrendously inefficient.
        def visit(group):
            group.set_state()

            # Draw domains using this group
            domain_map = self.group_map[group]
            for (_, mode, _), domain in domain_map.items():
                for list in vertex_lists:
                    if list.domain is domain:
                        list.draw(mode)

            # Sort and visit child groups of this group
            children = self.group_children.get(group)
            if children:
                children.sort()
                for child in children:
                    visit(child)

            group.unset_state()

        self.top_groups.sort()
        for group in self.top_groups:
            visit(group)

class AbstractGroup(object):
    '''Group of common OpenGL state.

    Before a vertex list is rendered, its group's OpenGL state is set; as are
    that state's ancestors' states.  This can be defined arbitrarily on
    subclasses; the default state change has no effect, and groups vertex
    lists only in the order in which they are drawn.
    '''
    def __init__(self, parent=None):
        '''Create a group.

        :Parameters:
            `parent` : `AbstractGroup`
                Group to contain this group; its state will be set before this
                state's.

        '''
        self.parent = parent
        
    def set_state(self):
        '''Apply the OpenGL state change.'''
        pass

    def unset_state(self):
        '''Repeal the OpenGL state change.'''
        pass

    def set_state_recursive(self):
        '''Set this group and its ancestry.

        Call this method if you are using a group in isolation: the
        parent groups will be called in top-down order, with this class's
        `set` being called last.
        '''
        if self.parent:
            self.parent.set_state_recursive()
        self.set_state()

    def unset_state_recursive(self):
        '''Unset this group and its ancestry.

        The inverse of `set_recursive`.
        '''
        self.unset_state()
        if self.parent:
            self.parent.unset_state_recursive()

class NullGroup(AbstractGroup):
    '''The default group class used when ``None`` is given to a batch.

    This implementation has no effect.
    '''
    pass

#: The default group.
#:
#: :type: `AbstractGroup`
null_group = NullGroup()

class TextureGroup(AbstractGroup):
    '''A group that enables and binds a texture.

    Texture groups are equal if their textures' targets and names are equal.
    '''
    # Don't use this, create your own group classes that are more specific.
    # This is just an example.
    def __init__(self, texture, parent=None):
        '''Create a texture group.

        :Parameters:
            `texture` : `Texture`
                Texture to bind.
            `parent` : `AbstractState`
                Parent group.

        '''
        super(TextureGroup, self).__init__(parent)
        self.texture = texture

    def set_state(self):
        glEnable(self.texture.target)
        glBindTexture(self.texture.target, self.texture.id)

    def unset_state(self):
        glDisable(self.texture.target)

    def __hash__(self):
        return hash((self.texture.target, self.texture.id, self.parent))

    def __eq__(self, other):
        return (self.texture.target == other.texture.target and
            self.texture.id == other.texture.id and
            self.parent == self.parent)

    def __repr__(self):
        return '%s(id=%d)' % (self.__class__.__name__, self.texture.id)

class OrderedGroup(AbstractGroup):
    '''A group with partial order.

    Ordered groups with a common parent are rendered in ascending order of
    their ``order`` field.  This is a useful way to render multiple layers of
    a scene within a single batch.
    '''
    # This can be useful as a top-level group, or as a superclass for other
    # groups that need to be ordered.
    #
    # As a top-level group it's useful because graphics can be composited in a
    # known order even if they don't know about each other or share any known
    # group.
    def __init__(self, order, parent=None):
        '''Create an ordered group.

        :Parameters:
            `order` : int
                Order of this group.
            `parent` : `AbstractGroup`
                Parent of this group.

        '''
        super(OrderedGroup, self).__init__(parent)
        self.order = order

    def __cmp__(self, other):
        if isinstance(other, OrderedGroup):
            return cmp(self.order, other.order)
        return -1

    def __eq__(self, other):
        return (self.__class__ is other.__class__ and
            self.order == other.order and
            self.parent == other.parent)

    def __hash__(self):
        return hash((self.order, self.parent))

    def __repr__(self):
        return '%s(%d)' % (self.__class__.__name__, self.order)