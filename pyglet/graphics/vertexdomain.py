#!/usr/bin/python
# $Id:$

'''Manage related vertex attributes within a single vertex domain.

A vertex "domain" consists of a set of attribute descriptions that together
describe the layout of one or more vertex buffers which are used together to
specify the vertices in a primitive.  Additionally, the domain manages the
buffers used to store the data and will resize them as necessary to accomodate
new vertices.

Domains can optionally be indexed, in which case they also manage a buffer
containing vertex indices.  This buffer is grown separately and has no size
relation to the attribute buffers.

Applications can create vertices (and optionally, indices) within a domain
with the `VertexDomain.create` method.  This returns a `VertexList`
representing the list of vertices created.  The vertex attribute data within
the group can be modified, and the changes will be made to the underlying
buffers automatically.

The entire domain can be efficiently drawn in one step with the
`VertexDomain.draw` method, assuming all the vertices comprise primitives of
the same OpenGL primitive mode.
'''

import ctypes
import re

from pyglet.gl import *
from pyglet.graphics import allocation, vertexattribute, vertexbuffer

_usage_format_re = re.compile(r'''
    (?P<attribute>[^/]*)
    (/ (?P<usage> static|dynamic|stream))?
''', re.VERBOSE)

_gl_usages = {
    'static': GL_STATIC_DRAW,
    'dynamic': GL_DYNAMIC_DRAW,
    'stream': GL_STREAM_DRAW,
}

def _nearest_pow2(v):
    # From http://graphics.stanford.edu/~seander/bithacks.html#RoundUpPowerOf2
    # Credit: Sean Anderson
    v -= 1
    v |= v >> 1
    v |= v >> 2
    v |= v >> 4
    v |= v >> 8
    v |= v >> 16
    return v + 1

def create_attribute_usage(format):
    '''Create an attribute and usage pair from a format string.  The
    format string is as documented in `pyglet.graphics.vertexattribute`, with
    the addition of an optional usage component::

        usage ::= attribute ( '/' ('static' | 'dynamic' | 'stream') )?

    If the usage is not given it defaults to 'dynamic'.
    
    Some examples:

    ``v3f/stream``
        3D vertex position using floats, for stream usage
    ``c4b/static``
        4-byte color attribute, for static usage

    :return: attribute, usage  
    '''
    match = _usage_format_re.match(format)
    attribute_format = match.group('attribute')
    attribute = vertexattribute.create_attribute(attribute_format)
    usage = match.group('usage')
    if usage:
        usage = _gl_usages[usage]
    else:
        usage = GL_DYNAMIC_DRAW

    return (attribute, usage)

def create_domain(*attribute_usage_formats):
    '''Create a vertex domain covering the given attribute usage formats.
    See documentation for `create_attribute_usage` and `create_attribute` for
    the grammar of these format strings.

    :rtype: `VertexDomain`
    '''
    attribute_usages = [create_attribute_usage(f) \
                        for f in attribute_usage_formats]
    return VertexDomain(attribute_usages)

def create_indexed_domain(*attribute_usage_formats):
    '''Create an indexed vertex domain covering the given attribute usage
    formats.  See documentation for `create_attribute_usage` and
    `create_attribute` for the grammar of these format strings.

    :rtype: `VertexDomain`
    '''
    attribute_usages = [create_attribute_usage(f) \
                        for f in attribute_usage_formats]
    return IndexedVertexDomain(attribute_usages)

class VertexDomain(object):
    '''Management of a set of vertex lists.

    Construction of a vertex domain is usually done with the `create_domain`
    function.
    '''
    _version = 0
    _initial_count = 16

    def __init__(self, attribute_usages):
        self.allocator = allocation.Allocator(self._initial_count)

        static_attributes = []
        attributes = []
        self.buffer_attributes = []   # list of (buffer, attributes)
        for attribute, usage in attribute_usages:
            if usage == GL_STATIC_DRAW:
                # Group attributes for interleaved buffer
                static_attributes.append(attribute)
            else:
                # Create non-interleaved buffer
                attributes.append(attribute)
                attribute.buffer = vertexbuffer.create_mappable_buffer(
                    attribute.stride * self.allocator.capacity, usage=usage)
                attribute.buffer.element_size = attribute.stride
                attribute.buffer.attributes = (attribute,)
                self.buffer_attributes.append(
                    (attribute.buffer, (attribute,)))

        # Create buffer for interleaved data
        if static_attributes:
            vertexattribute.interleave_attributes(static_attributes)
            stride = static_attributes[0].stride
            buffer = vertexbuffer.create_mappable_buffer(
                stride * self.allocator.capacity, usage=GL_STATIC_DRAW)
            buffer.element_size = stride
            self.buffer_attributes.append(
                (buffer, static_attributes))

            attributes.extend(static_attributes)
            for attribute in static_attributes:
                attribute.buffer = buffer

        # Create named attributes for each attribute
        self.attributes = attributes
        self.attribute_names = {}
        for attribute in attributes:
            if isinstance(attribute, vertexattribute.GenericAttribute):
                index = attribute.index
                if 'generic' not in self.attributes:
                    self.attributes['generic'] = {}
                assert index not in self.attributes['generic'], \
                    'More than one generic attribute with index %d' % index
                self.attribute_names['generic'][index] = attribute
            else:
                name = attribute.plural
                assert name not in self.attributes, \
                    'More than one "%s" attribute given' % name
                self.attribute_names[name] = attribute

    def _safe_alloc(self, count):
        '''Allocate vertices, resizing the buffers if necessary.'''
        try:
            return self.allocator.alloc(count)
        except allocation.AllocatorMemoryException, e:
            capacity = _nearest_pow2(e.requested_capacity)
            self._version += 1
            for buffer, _ in self.buffer_attributes:
                buffer.resize(capacity * buffer.element_size)
            self.allocator.set_capacity(capacity)
            return self.allocator.alloc(count)

    def _safe_realloc(self, start, count, new_count):
        '''Reallocate vertices, resizing the buffers if necessary.'''
        try:
            return self.allocator.realloc(start, count, new_count)
        except allocation.AllocatorMemoryException, e:
            capacity = _nearest_pow2(e.requested_capacity)
            self._version += 1
            for buffer, _ in self.buffer_attributes:
                buffer.resize(capacity * buffer.element_size)
            self.allocator.set_capacity(capacity)
            return self.allocator.realloc(start, count, new_count) 

    def create(self, count):
        '''Create a `VertexList` in this domain.

        :Parameters:
            `count` : int
                Number of vertices to create.

        :rtype: `VertexList`
        '''
        start = self._safe_alloc(count)
        return VertexList(self, start, count)

    def draw(self, mode, vertex_list=None):
        '''Draw vertices in the domain.
        
        If `vertex_list` is not specified, all vertices in the domain are
        drawn.  This is the most efficient way to render primitives.

        If `vertex_list` specifies a `VertexList`, only primitives in that
        list will be drawn.

        :Parameters:
            `mode` : int
                OpenGL drawing mode, e.g. ``GL_POINTS``, ``GL_LINES``, etc.
            `vertex_list` : `VertexList`
                Vertex list to draw, or ``None`` for all lists in this domain.

        '''
        glPushClientAttrib(GL_CLIENT_VERTEX_ARRAY_BIT)
        for buffer, attributes in self.buffer_attributes:
            buffer.bind()
            for attribute in attributes:
                attribute.enable()
                attribute.set_pointer(attribute.buffer.ptr)

        if vertex_list is not None:
            glDrawArrays(mode, vertex_list.start, vertex_list.count)
        else:
            starts, sizes = self.allocator.get_allocated_regions()
            primcount = len(starts)
            if primcount == 0:
                pass
            elif primcount == 1:
                # Common case
                glDrawArrays(mode, starts[0], sizes[0])
            elif gl_info.have_version(1, 4):
                starts = (GLint * primcount)(*starts)
                sizes = (GLsizei * primcount)(*sizes)
                glMultiDrawArrays(mode, starts, sizes, primcount)
            else:
                for start, size in zip(starts, sizes):
                    glDrawArrays(mode, start, size)
        
        for buffer, _ in self.buffer_attributes:
            buffer.unbind()
        glPopClientAttrib()

class VertexList(object):
    '''A list of vertices within a `VertexDomain`.  Use
    `VertexDomain.create` to construct this list.
    '''
    
    def __init__(self, domain, start, count):
        # TODO make private
        self.domain = domain
        self.start = start
        self.count = count
    
    def get_size(self):
        '''Get the number of vertices in the list.

        :rtype: int
        '''
        return self.count

    def get_domain(self):
        '''Get the domain this vertex list belongs to.

        :rtype: `VertexDomain`
        '''
        return self.domain

    def draw(self, mode):
        '''Draw this vertex list in the given OpenGL mode.

        :Parameters:
            `mode` : int
                OpenGL drawing mode, e.g. ``GL_POINTS``, ``GL_LINES``, etc.

        '''
        self.domain.draw(mode, self)
    
    def resize(self, count):
        '''Resize this group.
        
        :Parameters:
            `count` : int
                New number of vertices in the list. 

        '''
        new_start = self.domain._safe_realloc(self.start, self.count, count)
        if new_start != self.start:
            # Copy contents to new location
            for attribute in self.domain.attributes:
                old = attribute.get_region(attribute.buffer, 
                                           self.start, self.count)
                new = attribute.get_region(attribute.buffer, 
                                           new_start, self.count)
                new.array[:] = old.array[:]
                new.invalidate()
        self.start = new_start
        self.count = count
        self._colors_cache_version = None
        self._vertices_cache_version = None

    def delete(self):
        '''Delete this group.'''
        self.domain.allocator.dealloc(self.start, self.count)

    def migrate(self, domain):
        '''Move this group from its current domain and add to the specified
        one.  Attributes on domains must match.  (In practice, used to change
        parent state of some vertices).
        
        :Parameters:
            `domain` : `VertexDomain`
                Domain to migrate this vertex list to.

        '''
        assert domain.attribute_names.keys() == \
            self.domain.attribute_names.keys(), 'Domain attributes must match.'

        new_start = domain.allocator.alloc(self.count)
        for key, old_attribute in self.domain.attribute_names.items():
            old = old_attribute.get_region(old_attribute.buffer,
                                           self.start, self.count)
            new_attribute = domain.attribute_names[key]
            new = new_attribute.get_region(new_attribute.buffer,
                                           new_start, self.count)
            new.array[:] = old.array[:]
            new.invalidate()

        self.domain.allocator.dealloc(self.start, self.count)
        self.domain = domain
        self.start = new_start

    def _set_attribute_data(self, i, data):
        attribute = self.domain.attributes[i]
        # TODO without region
        region = attribute.get_region(attribute.buffer, self.start, self.count)
        region.array[:] = data
        region.invalidate()

    # ---

    def _get_colors(self):
        if (self._colors_cache_version != self.domain._version):
            domain = self.domain
            attribute = domain.attribute_names['colors']
            self._colors_cache = attribute.get_region(
                attribute.buffer, self.start, self.count)
            self._colors_cache_version = domain._version

        region = self._colors_cache
        region.invalidate()
        return region.array

    def _set_colors(self, data):
        self._get_colors()[:] = data

    _colors_cache = None
    _colors_cache_version = None
    colors = property(_get_colors, _set_colors, 
                      doc='''Array of color data.''')

    # ---

    def _get_fog_coords(self):
        if (self._fog_coords_cache_version != self.domain._version):
            domain = self.domain
            attribute = domain.attribute_names['fog_coords']
            self._fog_coords_cache = attribute.get_region(
                attribute.buffer, self.start, self.count)
            self._fog_coords_cache_version = domain._version

        region = self._fog_coords_cache
        region.invalidate()
        return region.array

    def _set_fog_coords(self, data):
        self._get_fog_coords()[:] = data

    _fog_coords_cache = None
    _fog_coords_cache_version = None
    fog_coords = property(_get_fog_coords, _set_fog_coords,
                          doc='''Array of fog coordinate data.''')

    # ---

    def _get_edge_flags(self):
        if (self._edge_flags_cache_version != self.domain._version):
            domain = self.domain
            attribute = domain.attribute_names['edge_flags']
            self._edge_flags_cache = attribute.get_region(
                attribute.buffer, self.start, self.count)
            self._edge_flags_cache_version = domain._version

        region = self._edge_flags_cache
        region.invalidate()
        return region.array

    def _set_edge_flags(self, data):
        self._get_edge_flags()[:] = data

    _edge_flags_cache = None
    _edge_flags_cache_version = None
    edge_flags = property(_get_edge_flags, _set_edge_flags,
                          doc='''Array of edge flag data.''')

    # ---

    def _get_normals(self):
        if (self._normals_cache_version != self.domain._version):
            domain = self.domain
            attribute = domain.attribute_names['normals']
            self._normals_cache = attribute.get_region(
                attribute.buffer, self.start, self.count)
            self._normals_cache_version = domain._version

        region = self._normals_cache
        region.invalidate()
        return region.array

    def _set_normals(self, data):
        self._get_normals()[:] = data

    _normals_cache = None
    _normals_cache_version = None
    normals = property(_get_normals, _set_normals,
                       doc='''Array of normal vector data.''')

    # ---

    def _get_secondary_colors(self):
        if (self._secondary_colors_cache_version != self.domain._version):
            domain = self.domain
            attribute = domain.attribute_names['secondary_colors']
            self._secondary_colors_cache = attribute.get_region(
                attribute.buffer, self.start, self.count)
            self._secondary_colors_cache_version = domain._version

        region = self._secondary_colors_cache
        region.invalidate()
        return region.array

    def _set_secondary_colors(self, data):
        self._get_secondary_colors()[:] = data

    _secondary_colors_cache = None
    _secondary_colors_cache_version = None
    secondary_colors = property(_get_secondary_colors, _set_secondary_colors,
                                doc='''Array of secondary color data.''')

    # ---

    _tex_coords_cache = None
    _tex_coords_cache_version = None

    def _get_tex_coords(self):
        if (self._tex_coords_cache_version != self.domain._version):
            domain = self.domain
            attribute = domain.attribute_names['tex_coords']
            self._tex_coords_cache = attribute.get_region(
                attribute.buffer, self.start, self.count)
            self._tex_coords_cache_version = domain._version

        region = self._tex_coords_cache
        region.invalidate()
        return region.array

    def _set_tex_coords(self, data):
        self._get_tex_coords()[:] = data

    tex_coords = property(_get_tex_coords, _set_tex_coords,
                          doc='''Array of texture coordinate data.''')

    # ---
    
    _vertices_cache = None
    _vertices_cache_version = None

    def _get_vertices(self):
        if (self._vertices_cache_version != self.domain._version):
            domain = self.domain
            attribute = domain.attribute_names['vertices']
            self._vertices_cache = attribute.get_region(
                attribute.buffer, self.start, self.count)
            self._vertices_cache_version = domain._version

        region = self._vertices_cache
        region.invalidate()
        return region.array

    def _set_vertices(self, data):
        self._get_vertices()[:] = data
    
    vertices = property(_get_vertices, _set_vertices,
                        doc='''Array of vertex coordinate data.''')

class IndexedVertexDomain(VertexDomain):
    '''Management of a set of indexed vertex lists.

    Construction of an indexed vertex domain is usually done with the
    `create_indexed_domain` function.
    '''
    _initial_index_count = 16

    def __init__(self, attribute_usages, index_gl_type=GL_UNSIGNED_INT):
        super(IndexedVertexDomain, self).__init__(attribute_usages)

        self.index_allocator = allocation.Allocator(self._initial_index_count)
        
        self.index_gl_type = index_gl_type
        self.index_c_type = vertexattribute._c_types[index_gl_type]
        self.index_element_size = ctypes.sizeof(self.index_c_type)
        self.index_buffer = vertexbuffer.create_mappable_buffer(
            self.index_allocator.capacity * self.index_element_size, 
            target=GL_ELEMENT_ARRAY_BUFFER)

    def _safe_index_alloc(self, count):
        '''Allocate indices, resizing the buffers if necessary.'''
        try:
            return self.index_allocator.alloc(count)
        except allocation.AllocatorMemoryException, e:
            capacity = _nearest_pow2(e.requested_capacity)
            self._version += 1
            self.index_buffer.resize(capacity * self.index_element_size)
            self.index_allocator.set_capacity(capacity)
            return self.index_allocator.alloc(count)

    def _safe_index_realloc(self, start, count, new_count):
        '''Reallocate indices, resizing the buffers if necessary.'''
        try:
            return self.index_allocator.realloc(start, count, new_count)
        except allocation.AllocatorMemoryException, e:
            capacity = _nearest_pow2(e.requested_capacity)
            self._version += 1
            self.index_buffer.resize(capacity * self.index_element_size)
            self.index_allocator.set_capacity(capacity)
            return self.index_allocator.realloc(start, count, new_count)

    def create(self, count, index_count):
        '''Create an `IndexedVertexList` in this domain.

        :Parameters:
            `count` : int
                Number of vertices to create
            `index_count`
                Number of indices to create

        '''
        start = self._safe_alloc(count)
        index_start = self._safe_index_alloc(index_count)
        return IndexedVertexList(self, start, count, index_start, index_count) 

    def get_index_region(self, start, count):
        '''Get a region of the index buffer.

        :Parameters:
            `start` : int
                Start of the region to map.
            `count` : int
                Number of indices to map.

        :rtype: Array of int
        '''
        byte_start = self.index_element_size * start
        byte_count = self.index_element_size * count
        ptr_type = ctypes.POINTER(self.index_c_type * count)
        return self.index_buffer.get_region(byte_start, byte_count, ptr_type)

    def draw(self, mode, vertex_list=None):
        '''Draw vertices in the domain.
        
        If `vertex_list` is not specified, all vertices in the domain are
        drawn.  This is the most efficient way to render primitives.

        If `vertex_list` specifies a `VertexList`, only primitives in that
        list will be drawn.

        :Parameters:
            `mode` : int
                OpenGL drawing mode, e.g. ``GL_POINTS``, ``GL_LINES``, etc.
            `vertex_list` : `IndexedVertexList`
                Vertex list to draw, or ``None`` for all lists in this domain.

        '''
        glPushClientAttrib(GL_CLIENT_VERTEX_ARRAY_BIT)
        for buffer, attributes in self.buffer_attributes:
            buffer.bind()
            for attribute in attributes:
                attribute.enable()
                attribute.set_pointer(attribute.buffer.ptr)
        self.index_buffer.bind()

        if vertex_list is not None:
            glDrawElements(mode, vertex_list.count, self.index_gl_type,
                self.index_buffer.ptr + vertex_list.start)
        else:
            starts, sizes = self.index_allocator.get_allocated_regions()
            primcount = len(starts)
            if primcount == 0:
                pass
            elif primcount == 1:
                # Common case
                glDrawElements(mode, sizes[0], self.index_gl_type,
                    self.index_buffer.ptr + starts[0])
            elif gl_info.have_version(1, 4):
                if not isinstance(self.index_buffer, 
                                  vertexbuffer.VertexBufferObject):
                    starts = [s + self.index_buffer.ptr for s in starts]
                starts = (GLuint * primcount)(*starts)
                sizes = (GLsizei * primcount)(*sizes)
                glMultiDrawElements(mode, sizes, self.index_gl_type, starts,
                                    primcount)
            else:
                for start, size in zip(starts, sizes):
                    glDrawElements(mode, size, self.index_gl_type,
                        self.index_buffer.ptr + start)
        
        self.index_buffer.unbind()
        for buffer, _ in self.buffer_attributes:
            buffer.unbind()
        glPopClientAttrib()

class IndexedVertexList(VertexList):
    '''A list of vertices within an `IndexedVertexDomain` that are indexed.
    Use `IndexedVertexDomain.create` to construct this list.
    '''
    def __init__(self, domain, start, count, index_start, index_count):
        super(IndexedVertexList, self).__init__(domain, start, count)

        self.index_start = index_start
        self.index_count = index_count

    def draw(self, mode):
        self.domain.draw(mode, self)

    def resize(self, count, index_count):
        '''Resize this group.

        :Parameters:
            `count` : int
                New number of vertices in the list. 
            `index_count` : int
                New number of indices in the list. 

        '''
        old_start = self.start
        super(IndexedVertexList, self).resize(count)

        # Change indices (because vertices moved)
        if old_start != self.start:
            diff = self.start - old_start
            self.indices[:] = map(lambda i: i + diff, self.indices)
        
        # Resize indices
        new_start = self.domain._safe_index_realloc(
            self.index_start, self.index_count, index_count)
        if new_start != self.index_start:
            old = self.domain.get_index_region(
                self.index_start, self.index_count)
            new = self.domain.get_index_region(
                self.index_start, self.index_count)
            new.array[:] = old.array[:]
            new.invalidate()
        self.index_start = new_start
        self.index_count = index_count
        self._indices_cache_version = None

    def delete(self):
        '''Delete this group.'''
        super(IndexedVertexList, self).delete()
        self.domain.index_allocator.dealloc(self.index_start, self.index_count)

    def _set_index_data(self, data):
        # TODO without region
        region = self.domain.get_index_region(
            self.index_start, self.index_count)
        region.array[:] = data
        region.invalidate()

    # ---

    def _get_indices(self):
        if self._indices_cache_version != self.domain._version:
            domain = self.domain
            self._indices_cache = domain.get_index_region(
                self.index_start, self.index_count)
            self._indices_cache_version = domain._version

        region = self._indices_cache
        region.invalidate()
        return region.array

    def _set_indices(self, data):
        self._get_indices()[:] = data

    _indices_cache = None
    _indices_cache_version = None
    indices = property(_get_indices, _set_indices, 
                       doc='''Array of index data.''')