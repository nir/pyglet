#!/usr/bin/python
# $Id:$

'''Formatted and unformatted document interfaces used by text layout.

Abstract representation
=======================

Styled text in pyglet is represented by one of the `AbstractDocument` classes,
which manage the state representation of text and style independently of how
it is loaded or rendered.  

A document consists of the document text (a Unicode string) and a set of
named style ranges.  For example, consider the following (artificial)
example::

    0    5   10   15   20
    The cat sat on the mat.
    +++++++        +++++++    "bold"
                ++++++      "italic"

If this example were to be rendered, "The cat" and "the mat" would be in bold,
and "on the" in italics.  Note that the second "the" is both bold and italic.

The document styles recorded for this example would be ``"bold"`` over ranges
(0-7, 15-22) and ``"italic"`` over range (12-18).  Overlapping styles are
permitted; unlike HTML and other structured markup, the ranges need not be
nested.

The document has no knowledge of the semantics of ``"bold"`` or ``"italic"``,
it stores only the style names.  The pyglet layout classes give meaning to
these style names in the way they are rendered; but you are also free to
invent your own style names (which will be ignored by the layout classes).
This can be useful to tag areas of interest in a document, or maintain
references back to the source material.

As well as text, the document can contain arbitrary elements represented by
`InlineElement`.  An inline element behaves like a single character in the
documented, but can be rendered by the application.

Document classes
================

Any class implementing `AbstractDocument` provides a an interface to a
document model as described above.  In theory a structured document such as
HTML or XML could export this model, though the classes provided by pyglet
implement only unstructured documents.

The `UnformattedDocument` class assumes any styles set are set over the entire
document.  So, regardless of the range specified when setting a ``"bold"``
style attribute, for example, the entire document will receive that style.

The `FormattedDocument` class implements the document model directly, using
the `RunList` class to represent style runs efficiently.

Style attributes
================

The following character style attribute names are recognised by pyglet:

``font_name``
    Font family name, as given to `pyglet.font.load`.
``font_size``
    Font size, in points.
``bold``
    Boolean.
``italic``
    Boolean.
``underline``
    4-tuple of ints in range (0, 255) giving RGBA underline color, or None
    (default) for no underline.
``kerning``
    Additional space to insert between glyphs, in points.  Defaults to 0.
``baseline``
    Offset of glyph baseline from line baseline, in points.  Positive values
    give a superscript, negative values give a subscript.  Defaults to 0.
``color``
    4-tuple of ints in range (0, 255) giving RGBA text color
``background_color``
    4-tuple of ints in range (0, 255) giving RGBA text background color; or
    ``None`` for no background fill.

The following paragraph style attribute names are recognised by pyglet.  Note
that paragraph styles are handled no differently from character styles by the
document: it is the application's responsibility to set the style over an
entire paragraph, otherwise results are undefined.

``align``
    ``left`` (default), ``center`` or ``right``.
``indent``
    Additional horizontal space to insert before the first 
``leading``
    Additional space to insert between consecutive lines within a paragraph,
    in points.  Defaults to 0.
``line_spacing``
    Distance between consecutive baselines in a paragraph, in points.
    Defaults to ``None``, which automatically calculates the tightest line
    spacing for each line based on the font ascent and descent.
``margin_left``
    Left paragraph margin, in pixels.
``margin_right``
    Right paragraph margin, in pixels.
``margin_top``
    Margin above paragraph, in pixels.
``margin_bottom``
    Margin below paragraph, in pixels.  Adjacent margins do not collapse.
``tab_stops``
    List of horizontal tab stops, in pixels, measured from the left edge of
    the text layout.  Defaults to the empty list.  When the tab stops
    are exhausted, they implicitly continue at 50 pixel intervals.
``wrap``
    Boolean.  If True (the default), text wraps within the width of the layout.

Other attributes can be used to store additional style information within the
document; it will be ignored by the built-in text classes.

All style attributes (including those not present in a document) default to
``None`` (including the so-called "boolean" styles listed above).  The meaning
of a ``None`` style is style- and application-dependent. 

:since: pyglet 1.1
'''

import re
import sys

from pyglet import event
from pyglet.text import runlist

_is_epydoc = hasattr(sys, 'is_epydoc') and sys.is_epydoc

#: The style attribute takes on multiple values in the document.
STYLE_INDETERMINATE = 'indeterminate'

class InlineElement(object):
    '''Arbitrary inline element positioned within a formatted document.

    Elements behave like a single glyph in the document.  They are
    measured by their horizontal advance, ascent above the baseline, and
    descent below the baseline.  
    
    The pyglet layout classes reserve space in the layout for elements and
    call the element's methods to ensure they are rendered at the
    appropriate position.

    If the size of a element (any of the `advance`, `ascent`, or `descent`
    instance variables) is modified it is the application's responsibility to
    trigger a reflow of the appropriate area in the affected layouts.  This
    can be done by forcing a style change over the element's position.

    :Ivariables:
        `ascent` : int
            Ascent of the element above the baseline, in pixels.
        `descent` : int
            Descent of the element below the baseline, in pixels.
            Typically negative.
        `advance` : int
            Width of the element, in pixels.

    '''
    def __init__(self, ascent, descent, advance):
        self.ascent = ascent
        self.descent = descent
        self.advance = advance
        self._position = None

    position = property(lambda self: self._position,
                        doc='''Position of the element within the
        document.  Read-only.

        :type: int
        ''')

    def place(self, layout, x, y):
        '''Construct an instance of the element at the given coordinates.

        Called when the element's position within a layout changes, either
        due to the initial condition, changes in the document or changes in
        the layout size.

        It is the responsibility of the element to clip itself against
        the layout boundaries, and position itself appropriately with respect
        to the layout's position and viewport offset.  
        
        The `TextLayout.top_state` graphics state implements this transform
        and clipping into window space.

        :Parameters:
            `layout` : `pyglet.text.layout.TextLayout`
                The layout the element moved within.
            `x` : int
                Position of the left edge of the element, relative
                to the left edge of the document, in pixels.
            `y` : int
                Position of the baseline, relative to the top edge of the
                document, in pixels.  Note that this is typically negative.

        '''
        raise NotImplementedError('abstract')

    def remove(self, layout):
        '''Remove this element from a layout.

        The couterpart of `add`; called when the element is no longer
        visible in the given layout.

        :Parameters:
            `layout` : `pyglet.text.layout.TextLayout`
                The layout the element was removed from.

        '''
        raise NotImplementedError('abstract')

class AbstractDocument(event.EventDispatcher):
    '''Abstract document interface used by all `pyglet.text` classes.

    This class can be overridden to interface pyglet with a third-party
    document format.  It may be easier to implement the document format in
    terms of one of the supplied concrete classes `FormattedDocument` or
    `UnformattedDocument`. 
    '''
    _previous_paragraph_re = re.compile(u'\n[^\n\u2029]*$')
    _next_paragraph_re = re.compile(u'[\n\u2029]')

    def __init__(self, text=''):
        super(AbstractDocument, self).__init__()
        self._text = ''
        self._elements = []
        if text:
            self.insert_text(0, text)

    def _get_text(self):
        return self._text

    def _set_text(self, text):
        self.delete_text(0, len(self._text))
        self.insert_text(0, text)
    
    text = property(_get_text, _set_text, 
                    doc='''Document text.
                   
        For efficient incremental updates, use the `insert_text` and
        `delete_text` methods instead of replacing this property.
        
        :type: str
        ''')

    def get_paragraph_start(self, pos):
        '''Get the starting position of a paragraph.

        :Parameters:
            `pos` : int
                Character position within paragraph.

        :rtype: int
        '''
        # Tricky special case where the $ in pattern matches before the \n at
        # the end of the string instead of the end of the string.
        if (self._text[:pos + 1].endswith('\n') or 
            self._text[:pos + 1].endswith(u'\u2029')):
            return pos

        m = self._previous_paragraph_re.search(self._text, 0, pos + 1)
        if not m:
            return 0
        return m.start() + 1

    def get_paragraph_end(self, pos):
        '''Get the end position of a paragraph.

        :Parameters:
            `pos` : int
                Character position within paragraph.

        :rtype: int
        '''
        m = self._next_paragraph_re.search(self._text, pos)
        if not m:
            return len(self._text)
        return m.start() + 1

    def get_style_runs(self, attribute):
        '''Get a style iterator over the given style attribute.

        :Parameters:
            `attribute` : str
                Name of style attribute to query.

        :rtype: `StyleRunsRangeIterator`
        '''
        raise NotImplementedError('abstract')

    def get_style(self, attribute, position):
        '''Get an attribute style at the given position.

        :Parameters:
            `attribute` : str
                Name of style attribute to query.
            `position` : int
                Character position of document to query.

        :return: The style set for the attribute at the given position.
        '''
        raise NotImplementedError('abstract')

    def get_style_range(self, attribute, start, end):
        '''Get an attribute style over the given range.

        If the style varies over the range, `STYLE_INDETERMINATE` is returned.

        :Parameters:
            `attribute` : str
                Name of style attribute to query.
            `start` : int
                Starting character position.
            `end` : int
                Ending character position (exclusive).

        :return: The style set for the attribute over the given range, or
            `STYLE_INDETERMINATE` if more than one value is set.
        '''
        iter = self.get_style_runs(attribute)
        _, value_end, value = iter.ranges(start, end).next()
        if value_end < end:
            return STYLE_INDETERMINATE
        else:
            return value

    def get_font_runs(self, dpi=None):
        '''Get a style iterator over the `pyglet.font.Font` instances used in
        the document.

        The font instances are created on-demand by inspection of the
        ``font_name``, ``font_size``, ``bold`` and ``italic`` style
        attributes.

        :Parameters:
            `dpi` : float
                Optional resolution to construct fonts at.  See
                `pyglet.font.load`.

        :rtype: `StyleRunsRangeIterator`
        '''
        raise NotImplementedError('abstract')

    def get_font(self, position, dpi=None):
        '''Get the font instance used at the given position.

        :see: `get_font_runs`

        :Parameters:
            `position` : int
                Character position of document to query.
            `dpi` : float
                Optional resolution to construct fonts at.  See
                `pyglet.font.load`.

        :rtype: `pyglet.font.Font`
        :return: The font at the given position.
        '''
        raise NotImplementedError('abstract')
    
    def insert_text(self, start, text, attributes=None):
        '''Insert text into the document.

        :Parameters:
            `start` : int
                Character insertion point within document.
            `text` : str
                Text to insert.
            `attributes` : dict
                Optional dictionary giving named style attributes of the
                inserted text.

        '''
        self._insert_text(start, text, attributes)
        self.dispatch_event('on_insert_text', start, text)

    def _insert_text(self, start, text, attributes):
        self._text = ''.join((self._text[:start], text, self._text[start:]))
        len_text = len(text)
        for element in self._elements:
            if element._position >= start:
                element._position += len_text

    def delete_text(self, start, end):
        '''Delete text from the document.

        :Parameters:
            `start` : int
                Starting character position to delete from.
            `end` : int
                Ending character position to delete to (exclusive).

        '''
        self._delete_text(start, end)
        self.dispatch_event('on_delete_text', start, end)

    def _delete_text(self, start, end):
        for element in list(self._elements):
            if start <= element.position < end:
                self._elements.remove(element)

        self._text = self._text[:start] + self._text[end:]

    def insert_element(self, position, element, attributes=None):
        '''Insert a element into the document.

        See the `InlineElement` class documentation for details of
        usage.

        :Parameters:
            `position` : int
                Character insertion point within document.
            `element` : `InlineElement`
                Element to insert.
            `attributes` : dict
                Optional dictionary giving named style attributes of the
                inserted text.

        '''
        assert element._position is None, \
            'Element is already in a document.'
        self.insert_text(position, '\0', attributes)
        element._position = position
        self._elements.append(element)
        self._elements.sort(key=lambda d:d.position)

    def get_element(self, position):
        '''Get the element at a specified position.

        :Parameters:
            `position` : int
                Position in the document of the element.

        :rtype: `InlineElement`
        '''
        for element in self._elements:
            if element._position == position:
                return element
        raise RuntimeError('No element at position %d' % position)

    def set_style(self, start, end, attributes):
        '''Set text style of some or all of the document.

        :Parameters:
            `start` : int
                Starting character position.
            `end` : int
                Ending character position (exclusive).
            `attributes` : dict
                Dictionary giving named style attributes of the text.

        '''
        self._set_style(start, end, attributes)
        self.dispatch_event('on_style_text', start, end, attributes)

    def _set_style(self, start, end, attributes):
        raise NotImplementedError('abstract')

    def set_paragraph_style(self, start, end, attributes):
        '''Set the style for a range of paragraphs.

        This is a convenience method for `set_style` that aligns the
        character range to the enclosing paragraph(s).

        :Parameters:
            `start` : int
                Starting character position.
            `end` : int
                Ending character position (exclusive).
            `attributes` : dict
                Dictionary giving named style attributes of the paragraphs.

        '''
        start = self.get_paragraph_start(start)
        end = self.get_paragraph_end(end)
        self._set_style(start, end, attributes)
        self.dispatch_event('on_style_text', start, end, attributes)

    if _is_epydoc:
        def on_insert_text(start, text):
            '''Text was inserted into the document.

            :Parameters:
                `start` : int
                    Character insertion point within document.
                `text` : str
                    The text that was inserted.

            :event:
            '''

        def on_delete_text(start, end):
            '''Text was deleted from the document.

            :Parameters:
                `start` : int
                    Starting character position of deleted text.
                `end` : int
                    Ending character position of deleted text (exclusive).

            :event:
            '''

        def on_style_text(start, end, attributes):
            '''Text character style was modified.

            :Parameters:
                `start` : int
                    Starting character position of modified text.
                `end` : int
                    Ending character position of modified text (exclusive).
                `attributes` : dict
                    Dictionary giving updated named style attributes of the
                    text.

            '''
AbstractDocument.register_event_type('on_insert_text')
AbstractDocument.register_event_type('on_delete_text')
AbstractDocument.register_event_type('on_style_text')

class UnformattedDocument(AbstractDocument):
    '''A document having uniform style over all text.

    Changes to the style of text within the document affects the entire
    document.  For convenience, the `position` parameters of the style methods
    may therefore be omitted.
    '''

    def __init__(self, text=''):
        super(UnformattedDocument, self).__init__(text)
        self.styles = {}

    def get_style_runs(self, attribute):
        value = self.styles.get(attribute)
        return runlist.ConstRunIterator(len(self.text), value)

    def get_style(self, attribute, position=None):
        return self.styles.get(attribute)

    def set_style(self, start, end, attributes):
        return super(UnformattedDocument, self).set_style(
            0, len(self.text), attributes)

    def _set_style(self, start, end, attributes):
        self.styles.update(attributes)

    def set_paragraph_style(self, start, end, attributes):
        return super(UnformattedDocument, self).set_paragraph_style(
            0, len(self.text), attributes)

    def get_font_runs(self, dpi=None):
        ft = self.get_font(dpi=dpi)
        return runlist.ConstRunIterator(len(self.text), ft)

    def get_font(self, position=None, dpi=None):
        from pyglet import font
        font_name = self.styles.get('font_name')
        font_size = self.styles.get('font_size')
        bold = self.styles.get('bold', False)
        italic = self.styles.get('italic', False)
        return font.load(font_name, font_size, 
                         bold=bool(bold), italic=bool(italic), dpi=dpi) 

    def get_element_runs(self):
        return runlist.ConstRunIterator(len(self._text), None)

class FormattedDocument(AbstractDocument):
    '''Simple implementation of a document that maintains text formatting.

    Changes to text style are applied according to the description in
    `AbstractDocument`.  All styles default to ``None``.
    '''

    def __init__(self, text=''):
        self._style_runs = {}
        super(FormattedDocument, self).__init__(text)

    def get_style_runs(self, attribute):
        try:
            return self._style_runs[attribute].get_run_iterator()
        except KeyError:
            return _no_style_range_iterator

    def get_style(self, attribute, position):
        try:
            return self._style_runs[attribute][position]
        except KeyError:
            return None

    def _set_style(self, start, end, attributes):
        for attribute, value in attributes.items():
            try:
                runs = self._style_runs[attribute]
            except KeyError:
                runs = self._style_runs[attribute] = runlist.RunList(0, None)
                runs.insert(0, len(self._text))
            runs.set_run(start, end, value)

    def get_font_runs(self, dpi=None):
        return _FontStyleRunsRangeIterator(
            self.get_style_runs('font_name'),
            self.get_style_runs('font_size'),
            self.get_style_runs('bold'),
            self.get_style_runs('italic'),
            dpi)

    def get_font(self, position, dpi=None):
        iter = self.get_font_runs(dpi)
        return iter[position]

    def get_element_runs(self):
        return _ElementIterator(self._elements, len(self._text))

    def _insert_text(self, start, text, attributes):
        super(FormattedDocument, self)._insert_text(start, text, attributes)

        len_text = len(text)
        for runs in self._style_runs.values():
            runs.insert(start, len_text)

        if attributes is not None:
            for attribute, value in attributes.items():
                try:
                    runs = self._style_runs[attribute]
                except KeyError:
                    runs = self._style_runs[attribute] = \
                        runlist.RunList(0, None)
                    runs.insert(0, len(self.text))
                runs.set_run(start, start + len_text, value)

    def _delete_text(self, start, end):
        super(FormattedDocument, self)._delete_text(start, end)
        for runs in self._style_runs.values():
            runs.delete(start, end)

def _iter_elements(elements, length):
    last = 0
    for element in elements:
        p = element.position
        yield last, p, None
        yield p, p + 1, element
        last = p + 1
    yield last, length, None

class _ElementIterator(runlist.RunIterator):
    def __init__(self, elements, length):
        self.next = _iter_elements(elements, length).next
        self.start, self.end, self.value = self.next()

class _FontStyleRunsRangeIterator(object):
    # XXX subclass runlist
    def __init__(self, font_names, font_sizes, bolds, italics, dpi):
        self.zip_iter = runlist.ZipRunIterator(
            (font_names, font_sizes, bolds, italics))
        self.dpi = dpi

    def ranges(self, start, end):
        from pyglet import font
        for start, end, styles in self.zip_iter.ranges(start, end):
            font_name, font_size, bold, italic = styles
            ft = font.load(font_name, font_size, 
                           bold=bool(bold), italic=bool(italic), 
                           dpi=self.dpi)
            yield start, end, ft

    def __getitem__(self, index):
        from pyglet import font
        font_name, font_size, bold, italic = self.zip_iter[index]
        return font.load(font_name, font_size,
                         bold=bool(bold), italic=bool(italic), 
                         dpi=self.dpi)

class _NoStyleRangeIterator(object):
    # XXX subclass runlist
    def ranges(self, start, end):
        yield start, end, None

    def __getitem__(self, index):
        return None
_no_style_range_iterator = _NoStyleRangeIterator()