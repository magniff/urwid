#!/usr/bin/python
#
# Urwid listbox class
#    Copyright (C) 2004-2007  Ian Ward
#
#    This library is free software; you can redistribute it and/or
#    modify it under the terms of the GNU Lesser General Public
#    License as published by the Free Software Foundation; either
#    version 2.1 of the License, or (at your option) any later version.
#
#    This library is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
#    Lesser General Public License for more details.
#
#    You should have received a copy of the GNU Lesser General Public
#    License along with this library; if not, write to the Free Software
#    Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA
#
# Urwid web site: http://excess.org/urwid/

from util import *
from canvas import *
from widget import *
import signals
from monitored_list import MonitoredList
from command_map import command_map


class ListWalkerError(Exception):
	pass

class ListWalker(object):
	__metaclass__ = signals.MetaSignals
	
	signals = ["modified"]

	def _modified(self):
		signals.emit_signal(self, "modified")
	

class PollingListWalker(object):  # NOT ListWalker subclass
	def __init__(self, contents):
		"""
		contents -- list to poll for changes
		"""
		self.contents = contents
		if not type(contents) == type([]) and not hasattr( 
			contents, '__getitem__' ):
			raise ListWalkerError, "SimpleListWalker expecting list like object, got: "+`contents`
		self.focus = 0
	
	def _clamp_focus(self):
		if self.focus >= len(self.contents):
			self.focus = len(self.contents)-1
	
	def get_focus(self):
		"""Return (focus widget, focus position)."""
		if len(self.contents) == 0: return None, None
		self._clamp_focus()
		return self.contents[self.focus], self.focus

	def set_focus(self, position):
		"""Set focus position."""
		assert type(position) == type(1)
		self.focus = position

	def get_next(self, start_from):
		"""
		Return (widget after start_from, position after start_from).
		"""
		pos = start_from + 1
		if len(self.contents) <= pos: return None, None
		return self.contents[pos],pos

	def get_prev(self, start_from):
		"""
		Return (widget before start_from, position before start_from).
		"""
		pos = start_from - 1
		if pos < 0: return None, None
		return self.contents[pos],pos


class SimpleListWalker(MonitoredList, ListWalker):
	def __init__(self, contents):
		"""
		contents -- list to copy into this object

		Changes made to this object (when it is treated as a list) are
		detected automatically and will cause ListBox objects using
		this list walker to be updated.
		"""
		if not type(contents) == type([]) and not hasattr(contents, '__getitem__'):
			raise ListWalkerError, "SimpleListWalker expecting list like object, got: "+`contents`
		MonitoredList.__init__(self, contents)
		self.focus = 0
	
	def _get_contents(self):
		"""
		Return self.

		Provides compatibility with old SimpleListWalker class.
		"""
		return self
	contents = property(_get_contents)

	def _modified(self):
		if self.focus >= len(self):
			self.focus = max(0, len(self)-1)
		ListWalker._modified(self)
	
	def set_modified_callback(self, callback):
		"""
		This function inherited from MonitoredList is not 
		implemented in SimleListWalker.
		
		Use connect_signal(list_walker, "modified", ...) instead.
		"""
		raise NotImplementedError('Use connect_signal('
			'list_walker, "modified", ...) instead.')
	
	def get_focus(self):
		"""Return (focus widget, focus position)."""
		if len(self) == 0: return None, None
		return self[self.focus], self.focus

	def set_focus(self, position):
		"""Set focus position."""
		assert type(position) == type(1)
		self.focus = position
		self._modified()

	def get_next(self, start_from):
		"""
		Return (widget after start_from, position after start_from).
		"""
		pos = start_from + 1
		if len(self) <= pos: return None, None
		return self[pos],pos

	def get_prev(self, start_from):
		"""
		Return (widget before start_from, position before start_from).
		"""
		pos = start_from - 1
		if pos < 0: return None, None
		return self[pos],pos
		

class ListBoxError(Exception):
	pass

class ListBox(BoxWidget):

	def __init__(self, body):
		"""
		body -- a ListWalker-like object that contains
			widgets to be displayed inside the list box
		"""
		if hasattr(body,'get_focus'):
			self.body = body
		else:
			self.body = PollingListWalker(body)

		try:
			connect_signal(self.body, "modified", self._invalidate)
		except NameError:
			# our list walker has no modified signal so we must not
			# cache our canvases because we don't know when our
			# content has changed
			self.render = nocache_widget_render_instance(self)

		# offset_rows is the number of rows between the top of the view
		# and the top of the focused item
		self.offset_rows = 0
		# inset_fraction is used when the focused widget is off the 
		# top of the view.  it is the fraction of the widget cut off 
		# at the top.  (numerator, denominator)
		self.inset_fraction = (0,1)

		# pref_col is the preferred column for the cursor when moving
		# between widgets that use the cursor (edit boxes etc.)
		self.pref_col = 'left'

		# variable for delayed focus change used by set_focus
		self.set_focus_pending = 'first selectable'
		
		# variable for delayed valign change used by set_focus_valign
		self.set_focus_valign_pending = None
		
	
	def calculate_visible(self, size, focus=False ):
		""" Return (middle,top,bottom) or None,None,None.

		middle -- ( row offset(when +ve) or inset(when -ve),
			focus widget, focus position, focus rows, 
			cursor coords or None )
		top -- ( # lines to trim off top, 
			list of (widget, position, rows) tuples above focus
			in order from bottom to top )
		bottom -- ( # lines to trim off bottom, 
			list of (widget, position, rows) tuples below focus
			in order from top to bottom )
		"""
		(maxcol, maxrow) = size

		# 0. set the focus if a change is pending
		if self.set_focus_pending or self.set_focus_valign_pending:
			self._set_focus_complete( (maxcol, maxrow), focus )

		# 1. start with the focus widget
		focus_widget, focus_pos = self.body.get_focus()
		if focus_widget is None: #list box is empty?
			return None,None,None
		top_pos = bottom_pos = focus_pos
		
		offset_rows, inset_rows = self.get_focus_offset_inset(
			(maxcol,maxrow))
		#    force at least one line of focus to be visible
		if maxrow and offset_rows >= maxrow:
			offset_rows = maxrow -1
		
		#    adjust position so cursor remains visible
		cursor = None
		if maxrow and focus_widget.selectable() and focus:
			if hasattr(focus_widget,'get_cursor_coords'):
				cursor=focus_widget.get_cursor_coords((maxcol,))
		
		if cursor is not None:
			cx, cy = cursor
			effective_cy = cy + offset_rows - inset_rows
			
			if effective_cy < 0: # cursor above top?
				inset_rows = cy
			elif effective_cy >= maxrow: # cursor below bottom?
				offset_rows = maxrow - cy -1
		
		#    set trim_top by focus trimmimg
		trim_top = inset_rows
		focus_rows = focus_widget.rows((maxcol,),True)
		
		# 2. collect the widgets above the focus
		pos = focus_pos
		fill_lines = offset_rows
		fill_above = []
		top_pos = pos
		while fill_lines > 0:
			prev, pos = self.body.get_prev( pos )
			if prev is None: # run out of widgets above?
				offset_rows -= fill_lines
				break
			top_pos = pos
	
			p_rows = prev.rows( (maxcol,) )
			fill_above.append( (prev, pos, p_rows) )
			if p_rows > fill_lines: # crosses top edge?
				trim_top = p_rows-fill_lines
				break
			fill_lines -= p_rows
		
		trim_bottom = focus_rows + offset_rows - inset_rows - maxrow
		if trim_bottom < 0: trim_bottom = 0

		# 3. collect the widgets below the focus
		pos = focus_pos
		fill_lines = maxrow - focus_rows - offset_rows + inset_rows
		fill_below = []
		while fill_lines > 0:
			next, pos = self.body.get_next( pos )
			if next is None: # run out of widgets below?
				break
			bottom_pos = pos
				
			n_rows = next.rows( (maxcol,) )
			fill_below.append( (next, pos, n_rows) )
			if n_rows > fill_lines: # crosses bottom edge?
				trim_bottom = n_rows-fill_lines
				fill_lines -= n_rows
				break
			fill_lines -= n_rows

		# 4. fill from top again if necessary & possible
		fill_lines = max(0, fill_lines)
		
		if fill_lines >0 and trim_top >0:
			if fill_lines <= trim_top:
				trim_top -= fill_lines
				offset_rows += fill_lines
				fill_lines = 0
			else:
				fill_lines -= trim_top
				offset_rows += trim_top
				trim_top = 0
		pos = top_pos
		while fill_lines > 0:
			prev, pos = self.body.get_prev( pos )
			if prev is None:
				break

			p_rows = prev.rows( (maxcol,) )
			fill_above.append( (prev, pos, p_rows) )
			if p_rows > fill_lines: # more than required
				trim_top = p_rows-fill_lines
				offset_rows += fill_lines
				break
			fill_lines -= p_rows
			offset_rows += p_rows
		
		# 5. return the interesting bits
		return ((offset_rows - inset_rows, focus_widget, 
				focus_pos, focus_rows, cursor ),
			(trim_top, fill_above), (trim_bottom, fill_below))

	
	def render(self, size, focus=False ):
		"""
		Render listbox and return canvas.
		"""
		(maxcol, maxrow) = size

		middle, top, bottom = self.calculate_visible( 
			(maxcol, maxrow), focus=focus)
		if middle is None:
			return SolidCanvas(" ", maxcol, maxrow)
		
		_ignore, focus_widget, focus_pos, focus_rows, cursor = middle
		trim_top, fill_above = top
		trim_bottom, fill_below = bottom

		combinelist = []
		rows = 0
		fill_above.reverse() # fill_above is in bottom-up order
		for widget,w_pos,w_rows in fill_above:
			canvas = widget.render((maxcol,))
			if w_rows != canvas.rows():
				raise ListBoxError, "Widget %s at position %s within listbox calculated %d rows but rendered %d!"% (`widget`,`w_pos`,w_rows, canvas.rows())
			rows += w_rows
			combinelist.append((canvas, w_pos, False))
		
		focus_canvas = focus_widget.render((maxcol,), focus=focus)

		if focus_canvas.rows() != focus_rows:
			raise ListBoxError, "Focus Widget %s at position %s within listbox calculated %d rows but rendered %d!"% (`focus_widget`,`focus_pos`,focus_rows, focus_canvas.rows())
		c_cursor = focus_canvas.cursor
		if cursor != c_cursor:
			raise ListBoxError, "Focus Widget %s at position %s within listbox calculated cursor coords %s but rendered cursor coords %s!" %(`focus_widget`,`focus_pos`,`cursor`,`c_cursor`)
			
		rows += focus_rows
		combinelist.append((focus_canvas, focus_pos, True))
		
		for widget,w_pos,w_rows in fill_below:
			canvas = widget.render((maxcol,))
			if w_rows != canvas.rows():
				raise ListBoxError, "Widget %s at position %s within listbox calculated %d rows but rendered %d!"% (`widget`,`w_pos`,w_rows, canvas.rows())
			rows += w_rows
			combinelist.append((canvas, w_pos, False))
		
		final_canvas = CanvasCombine(combinelist)
		
		if trim_top:	
			final_canvas.trim(trim_top)
			rows -= trim_top
		if trim_bottom:	
			final_canvas.trim_end(trim_bottom)
			rows -= trim_bottom
		
		assert rows <= maxrow, "Listbox contents too long!  Probably urwid's fault (please report): %s" % `top,middle,bottom`
		
		if rows < maxrow:
			bottom_pos = focus_pos
			if fill_below: bottom_pos = fill_below[-1][1]
			assert trim_bottom==0 and self.body.get_next(bottom_pos) == (None,None), "Listbox contents too short!  Probably urwid's fault (please report): %s" % `top,middle,bottom`
			final_canvas.pad_trim_top_bottom(0, maxrow - rows)

		return final_canvas


	def set_focus_valign(self, valign):
		"""Set the focus widget's display offset and inset.

		valign -- one of:
			'top', 'middle', 'bottom'
			('fixed top', rows)
			('fixed bottom', rows)
			('relative', percentage 0=top 100=bottom)
		"""
		vt,va,ht,ha=decompose_valign_height(valign,None,ListBoxError)
		self.set_focus_valign_pending = vt,va


	def set_focus(self, position, coming_from=None):
		"""
		Set the focus position and try to keep the old focus in view.

		position -- a position compatible with self.body.set_focus
		coming_from -- set to 'above' or 'below' if you know that
		               old position is above or below the new position.
		"""
		assert coming_from in ('above', 'below', None)
		focus_widget, focus_pos = self.body.get_focus()
		
		self.set_focus_pending = coming_from, focus_widget, focus_pos
		self.body.set_focus( position )

	def get_focus(self):
		"""
		Return a (focus widget, focus position) tuple.
		"""
		return self.body.get_focus()

	def _set_focus_valign_complete(self, size, focus):
		"""
		Finish setting the offset and inset now that we have have a 
		maxcol & maxrow.
		"""
		(maxcol, maxrow) = size
		vt,va = self.set_focus_valign_pending
		self.set_focus_valign_pending = None
		self.set_focus_pending = None

		focus_widget, focus_pos = self.body.get_focus()
		if focus_widget is None:
			return
		
		rows = focus_widget.rows((maxcol,), focus)
		rtop, rbot = calculate_filler( vt, va, 'fixed', rows, 
			None, maxrow )

		self.shift_focus((maxcol, maxrow), rtop)
		
	def _set_focus_first_selectable(self, size, focus):
		"""
		Choose the first visible, selectable widget below the
		current focus as the focus widget.
		"""
		(maxcol, maxrow) = size
		self.set_focus_valign_pending = None
		self.set_focus_pending = None
		middle, top, bottom = self.calculate_visible( 
			(maxcol, maxrow), focus=focus)
		if middle is None:
			return
		
		row_offset, focus_widget, focus_pos, focus_rows, cursor = middle
		trim_top, fill_above = top
		trim_bottom, fill_below = bottom

		if focus_widget.selectable():
			return

		if trim_bottom:
			fill_below = fill_below[:-1]
		new_row_offset = row_offset + focus_rows
		for widget, pos, rows in fill_below:
			if widget.selectable():
				self.body.set_focus(pos)
				self.shift_focus((maxcol, maxrow), 
					new_row_offset)
				return
			new_row_offset += rows

	def _set_focus_complete(self, size, focus):
		"""
		Finish setting the position now that we have maxcol & maxrow.
		"""
		(maxcol, maxrow) = size
		self._invalidate()
		if self.set_focus_pending == "first selectable":
			return self._set_focus_first_selectable(
				(maxcol,maxrow), focus)
		if self.set_focus_valign_pending is not None:
			return self._set_focus_valign_complete(
				(maxcol,maxrow), focus)
		coming_from, focus_widget, focus_pos = self.set_focus_pending
		self.set_focus_pending = None
		
		# new position
		new_focus_widget, position = self.body.get_focus()
		if focus_pos == position:
			# do nothing
			return
			
		# restore old focus temporarily
		self.body.set_focus(focus_pos)
				
		middle,top,bottom=self.calculate_visible((maxcol,maxrow),focus)
		focus_offset, focus_widget, focus_pos, focus_rows, cursor=middle
		trim_top, fill_above = top
		trim_bottom, fill_below = bottom
		
		offset = focus_offset
		for widget, pos, rows in fill_above:
			offset -= rows
			if pos == position:
				self.change_focus((maxcol, maxrow), pos,
					offset, 'below' )
				return

		offset = focus_offset + focus_rows
		for widget, pos, rows in fill_below:
			if pos == position:
				self.change_focus((maxcol, maxrow), pos,
					offset, 'above' )
				return
			offset += rows

		# failed to find widget among visible widgets
		self.body.set_focus( position )
		widget, position = self.body.get_focus()
		rows = widget.rows((maxcol,), focus)

		if coming_from=='below':
			offset = 0
		elif coming_from=='above':
			offset = maxrow-rows
		else:
			offset = (maxrow-rows)/2
		self.shift_focus((maxcol, maxrow), offset)
	

	def shift_focus(self, size, offset_inset):
		"""Move the location of the current focus relative to the top.
		
		offset_inset -- either the number of rows between the 
		  top of the listbox and the start of the focus widget (+ve
		  value) or the number of lines of the focus widget hidden off 
		  the top edge of the listbox (-ve value) or 0 if the top edge
		  of the focus widget is aligned with the top edge of the
		  listbox
		"""
		(maxcol, maxrow) = size
		
		if offset_inset >= 0:
			if offset_inset >= maxrow:
				raise ListBoxError, "Invalid offset_inset: %s, only %s rows in list box"% (`offset_inset`, `maxrow`)
			self.offset_rows = offset_inset
			self.inset_fraction = (0,1)
		else:
			target, _ignore = self.body.get_focus()
			tgt_rows = target.rows( (maxcol,), True )
			if offset_inset + tgt_rows <= 0:
				raise ListBoxError, "Invalid offset_inset: %s, only %s rows in target!" %(`offset_inset`, `tgt_rows`)
			self.offset_rows = 0
			self.inset_fraction = (-offset_inset,tgt_rows)
		self._invalidate()
				
	def update_pref_col_from_focus(self, size):
		"""Update self.pref_col from the focus widget."""
		(maxcol, maxrow) = size
		
		widget, old_pos = self.body.get_focus()
		if widget is None: return

		pref_col = None
		if hasattr(widget,'get_pref_col'):
			pref_col = widget.get_pref_col((maxcol,))
		if pref_col is None and hasattr(widget,'get_cursor_coords'):
			coords = widget.get_cursor_coords((maxcol,))
			if type(coords) == type(()):
				pref_col,y = coords
		if pref_col is not None: 
			self.pref_col = pref_col


	def change_focus(self, size, position, 
			offset_inset = 0, coming_from = None, 
			cursor_coords = None, snap_rows = None):
		"""Change the current focus widget.
		
		position -- a position compatible with self.body.set_focus
		offset_inset_rows -- either the number of rows between the 
		  top of the listbox and the start of the focus widget (+ve
		  value) or the number of lines of the focus widget hidden off 
		  the top edge of the listbox (-ve value) or 0 if the top edge
		  of the focus widget is aligned with the top edge of the
		  listbox (default if unspecified)
		coming_from -- eiter 'above', 'below' or unspecified (None)
		cursor_coords -- (x, y) tuple indicating the desired
		  column and row for the cursor, a (x,) tuple indicating only
		  the column for the cursor, or unspecified (None)
		snap_rows -- the maximum number of extra rows to scroll
		  when trying to "snap" a selectable focus into the view
		"""
		(maxcol, maxrow) = size
		
		# update pref_col before change
		if cursor_coords:
			self.pref_col = cursor_coords[0]
		else:
			self.update_pref_col_from_focus((maxcol,maxrow))

		self._invalidate()
		self.body.set_focus(position)
		target, _ignore = self.body.get_focus()
		tgt_rows = target.rows( (maxcol,), True)
		if snap_rows is None:
			snap_rows = maxrow-1

		# "snap" to selectable widgets
		align_top = 0
		align_bottom = maxrow - tgt_rows
		
		if ( coming_from == 'above' 
				and target.selectable()
				and offset_inset > align_bottom
				and align_bottom >= offset_inset-snap_rows ):
			offset_inset = align_bottom
			
		if ( coming_from == 'below' 
				and target.selectable() 
				and offset_inset < align_top
				and align_top <= offset_inset+snap_rows ):
			offset_inset = align_top
		
		# convert offset_inset to offset_rows or inset_fraction
		if offset_inset >= 0:
			self.offset_rows = offset_inset
			self.inset_fraction = (0,1)
		else:
			if offset_inset + tgt_rows <= 0:
				raise ListBoxError, "Invalid offset_inset: %s, only %s rows in target!" %(offset_inset, tgt_rows)
			self.offset_rows = 0
			self.inset_fraction = (-offset_inset,tgt_rows)
		
		if cursor_coords is None:
			if coming_from is None: 
				return # must either know row or coming_from
			cursor_coords = (self.pref_col,)
		
		if not hasattr(target,'move_cursor_to_coords'):
			return
			
		attempt_rows = []
		
		if len(cursor_coords) == 1:
			# only column (not row) specified
			# start from closest edge and move inwards
			(pref_col,) = cursor_coords
			if coming_from=='above':
				attempt_rows = range( 0, tgt_rows )
			else:
				assert coming_from == 'below', "must specify coming_from ('above' or 'below') if cursor row is not specified"
				attempt_rows = range( tgt_rows, -1, -1)
		else:
			# both column and row specified
			# start from preferred row and move back to closest edge
			(pref_col, pref_row) = cursor_coords
			if pref_row < 0 or pref_row >= tgt_rows:
				raise ListBoxError, "cursor_coords row outside valid range for target. pref_row:%s target_rows:%s"%(`pref_row`,`tgt_rows`)

			if coming_from=='above':
				attempt_rows = range( pref_row, -1, -1 )
			elif coming_from=='below':
				attempt_rows = range( pref_row, tgt_rows )
			else:
				attempt_rows = [pref_row]

		for row in attempt_rows:
			if target.move_cursor_to_coords((maxcol,),pref_col,row):
				break

	def get_focus_offset_inset(self, size):
		"""Return (offset rows, inset rows) for focus widget."""
		(maxcol, maxrow) = size
		focus_widget, pos = self.body.get_focus()
		focus_rows = focus_widget.rows((maxcol,), True)
		offset_rows = self.offset_rows
		inset_rows = 0
		if offset_rows == 0:
			inum, iden = self.inset_fraction
			if inum < 0 or iden < 0 or inum >= iden:
				raise ListBoxError, "Invalid inset_fraction: %s"%`self.inset_fraction`
			inset_rows = focus_rows * inum / iden
			assert inset_rows < focus_rows, "urwid inset_fraction error (please report)"
		return offset_rows, inset_rows


	def make_cursor_visible(self, size):
		"""Shift the focus widget so that its cursor is visible."""
		(maxcol, maxrow) = size
		
		focus_widget, pos = self.body.get_focus()
		if focus_widget is None:
			return
		if not focus_widget.selectable(): 
			return
		if not hasattr(focus_widget,'get_cursor_coords'): 
			return
		cursor = focus_widget.get_cursor_coords((maxcol,))
		if cursor is None: 
			return
		cx, cy = cursor
		offset_rows, inset_rows = self.get_focus_offset_inset(
			(maxcol, maxrow))
		
		if cy < inset_rows:
			self.shift_focus( (maxcol,maxrow), - (cy) )
			return
			
		if offset_rows - inset_rows + cy >= maxrow:
			self.shift_focus( (maxcol,maxrow), maxrow-cy-1 )
			return


	def keypress(self, size, key):
		"""Move selection through the list elements scrolling when 
		necessary. 'up' and 'down' are first passed to widget in focus
		in case that widget can handle them. 'page up' and 'page down'
		are always handled by the ListBox.
		
		Keystrokes handled by this widget are:
		 'up'        up one line (or widget)
		 'down'      down one line (or widget)
		 'page up'   move cursor up one listbox length
		 'page down' move cursor down one listbox length
		"""
		(maxcol, maxrow) = size

		if self.set_focus_pending or self.set_focus_valign_pending:
			self._set_focus_complete( (maxcol,maxrow), focus=True )
			
		focus_widget, pos = self.body.get_focus()
		if focus_widget is None: # empty listbox, can't do anything
			return key
			
		if key not in ['page up','page down']:
			if focus_widget.selectable():
				key = focus_widget.keypress((maxcol,),key)
			if key is None: 
				self.make_cursor_visible((maxcol,maxrow))
				return
		
		# pass off the heavy lifting
		if command_map[key] == 'cursor up':
			return self._keypress_up((maxcol, maxrow))
			
		if command_map[key] == 'cursor down':
			return self._keypress_down((maxcol, maxrow))

		if command_map[key] == 'cursor page up':
			return self._keypress_page_up((maxcol, maxrow))
			
		if command_map[key] == 'cursor page down':
			return self._keypress_page_down((maxcol, maxrow))

		return key
		
	
	def _keypress_up(self, size):
		(maxcol, maxrow) = size
	
		middle, top, bottom = self.calculate_visible(
			(maxcol,maxrow), True)
		if middle is None: return 'up'
		
		focus_row_offset,focus_widget,focus_pos,_ignore,cursor = middle
		trim_top, fill_above = top
		
		row_offset = focus_row_offset
		
		# look for selectable widget above
		pos = focus_pos
		widget = None
		for widget, pos, rows in fill_above:
			row_offset -= rows
			if widget.selectable():
				# this one will do
				self.change_focus((maxcol,maxrow), pos,
					row_offset, 'below')
				return
		
		# at this point we must scroll
		row_offset += 1
		self._invalidate()
		
		if row_offset > 0:
			# need to scroll in another candidate widget
			widget, pos = self.body.get_prev(pos)
			if widget is None:
				# cannot scroll any further
				return 'up' # keypress not handled
			rows = widget.rows((maxcol,), True)
			row_offset -= rows
			if widget.selectable():
				# this one will do
				self.change_focus((maxcol,maxrow), pos,
					row_offset, 'below')
				return
		
		if not focus_widget.selectable() or focus_row_offset+1>=maxrow:
			# just take top one if focus is not selectable
			# or if focus has moved out of view
			if widget is None:
				self.shift_focus((maxcol,maxrow), row_offset)
				return
			self.change_focus((maxcol,maxrow), pos,
				row_offset, 'below')
			return

		# check if cursor will stop scroll from taking effect
		if cursor is not None:
			x,y = cursor
			if y+focus_row_offset+1 >= maxrow:
				# cursor position is a problem, 
				# choose another focus
				if widget is None:
					# try harder to get prev widget
					widget, pos = self.body.get_prev(pos)
					if widget is None:
						return # can't do anything
					rows = widget.rows((maxcol,), True)
					row_offset -= rows
				
				if -row_offset >= rows:
					# must scroll further than 1 line
					row_offset = - (rows-1)
				
				self.change_focus((maxcol,maxrow),pos,
					row_offset, 'below')
				return

		# if all else fails, just shift the current focus.
		self.shift_focus((maxcol,maxrow), focus_row_offset+1)
			
			
				
	def _keypress_down(self, size):
		(maxcol, maxrow) = size
	
		middle, top, bottom = self.calculate_visible(
			(maxcol,maxrow), True)
		if middle is None: return 'down'
			
		focus_row_offset,focus_widget,focus_pos,focus_rows,cursor=middle
		trim_bottom, fill_below = bottom
		
		row_offset = focus_row_offset + focus_rows
		rows = focus_rows
	
		# look for selectable widget below
		pos = focus_pos
		widget = None
		for widget, pos, rows in fill_below:
			if widget.selectable():
				# this one will do
				self.change_focus((maxcol,maxrow), pos,
					row_offset, 'above')
				return
			row_offset += rows
		
		# at this point we must scroll
		row_offset -= 1
		self._invalidate()
		
		if row_offset < maxrow:
			# need to scroll in another candidate widget
			widget, pos = self.body.get_next(pos)
			if widget is None:
				# cannot scroll any further
				return 'down' # keypress not handled
			if widget.selectable():
				# this one will do
				self.change_focus((maxcol,maxrow), pos,
					row_offset, 'above')
				return
			rows = widget.rows((maxcol,))
			row_offset += rows
		
		if not focus_widget.selectable() or focus_row_offset+focus_rows-1 <= 0:
			# just take bottom one if current is not selectable
			# or if focus has moved out of view
			if widget is None:
				self.shift_focus((maxcol,maxrow), 
					row_offset-rows)
				return
			# FIXME: catch this bug in testcase
			#self.change_focus((maxcol,maxrow), pos,
			#	row_offset+rows, 'above')
			self.change_focus((maxcol,maxrow), pos,
				row_offset-rows, 'above')
			return

		# check if cursor will stop scroll from taking effect
		if cursor is not None:
			x,y = cursor
			if y+focus_row_offset-1 < 0:
				# cursor position is a problem,
				# choose another focus
				if widget is None:
					# try harder to get next widget
					widget, pos = self.body.get_next(pos)
					if widget is None:
						return # can't do anything
				else:
					row_offset -= rows

				if row_offset >= maxrow:
					# must scroll further than 1 line
					row_offset = maxrow-1
					
				self.change_focus((maxcol,maxrow),pos,
					row_offset, 'above', )
				return

		# if all else fails, keep the current focus.
		self.shift_focus((maxcol,maxrow), focus_row_offset-1)
				
				
			
	def _keypress_page_up(self, size):
		(maxcol, maxrow) = size
		
		middle, top, bottom = self.calculate_visible(
			(maxcol,maxrow), True)
		if middle is None: return 'page up'
			
		row_offset, focus_widget, focus_pos, focus_rows, cursor = middle
		trim_top, fill_above = top

		# topmost_visible is row_offset rows above top row of 
		# focus (+ve) or -row_offset rows below top row of focus (-ve)
		topmost_visible = row_offset
		
		# scroll_from_row is (first match)
		# 1. topmost visible row if focus is not selectable
		# 2. row containing cursor if focus has a cursor
		# 3. top row of focus widget if it is visible
		# 4. topmost visible row otherwise
		if not focus_widget.selectable():
			scroll_from_row = topmost_visible
		elif cursor is not None:
			x,y = cursor
			scroll_from_row = -y
		elif row_offset >= 0:
			scroll_from_row = 0
		else:
			scroll_from_row = topmost_visible
		
		# snap_rows is maximum extra rows to scroll when
		# snapping to new a focus
		snap_rows = topmost_visible - scroll_from_row

		# move row_offset to the new desired value (1 "page" up)
		row_offset = scroll_from_row + maxrow
		
		# not used below:
		scroll_from_row = topmost_visible = None
		
		
		# gather potential target widgets
		t = []
		# add current focus
		t.append((row_offset,focus_widget,focus_pos,focus_rows))
		pos = focus_pos
		# include widgets from calculate_visible(..)
		for widget, pos, rows in fill_above:
			row_offset -= rows
			t.append( (row_offset, widget, pos, rows) )
		# add newly visible ones, including within snap_rows
		snap_region_start = len(t)
		while row_offset > -snap_rows:
			widget, pos = self.body.get_prev(pos)
			if widget is None: break
			rows = widget.rows((maxcol,))
			row_offset -= rows
			# determine if one below puts current one into snap rgn
			if row_offset > 0:
				snap_region_start += 1
			t.append( (row_offset, widget, pos, rows) ) 

		# if we can't fill the top we need to adjust the row offsets
		row_offset, w, p, r = t[-1]
		if row_offset > 0:
			adjust = - row_offset
			t = [(ro+adjust, w, p, r) for (ro,w,p,r) in t]	

		# if focus_widget (first in t) is off edge, remove it
		row_offset, w, p, r = t[0]
		if row_offset >= maxrow:
			del t[0]
			snap_region_start -= 1
		
		# we'll need this soon
		self.update_pref_col_from_focus((maxcol,maxrow))
			
		# choose the topmost selectable and (newly) visible widget
		# search within snap_rows then visible region
		search_order = ( range( snap_region_start, len(t))
				+ range( snap_region_start-1, -1, -1 ) )
		#assert 0, `t, search_order`
		bad_choices = []
		cut_off_selectable_chosen = 0
		for i in search_order:
			row_offset, widget, pos, rows = t[i]
			if not widget.selectable(): 
				continue

			# try selecting this widget
			pref_row = max(0, -row_offset)
			
			# if completely within snap region, adjust row_offset
			if rows + row_offset <= 0:
				self.change_focus( (maxcol,maxrow), pos,
					-(rows-1), 'below',
					(self.pref_col, rows-1),
					snap_rows-((-row_offset)-(rows-1)))
			else:
				self.change_focus( (maxcol,maxrow), pos,
					row_offset, 'below', 
					(self.pref_col, pref_row), snap_rows )
			
			# if we're as far up as we can scroll, take this one
			if (fill_above and self.body.get_prev(fill_above[-1][1])
				== (None,None) ):
				pass #return
			
			# find out where that actually puts us
			middle, top, bottom = self.calculate_visible(
				(maxcol,maxrow), True)
			act_row_offset, _ign1, _ign2, _ign3, _ign4 = middle
			
			# discard chosen widget if it will reduce scroll amount
			# because of a fixed cursor (absolute last resort)
			if act_row_offset > row_offset+snap_rows:
				bad_choices.append(i)
				continue
			if act_row_offset < row_offset:
				bad_choices.append(i)
				continue
			
			# also discard if off top edge (second last resort)
			if act_row_offset < 0:
				bad_choices.append(i)
				cut_off_selectable_chosen = 1
				continue
			
			return
			
		# anything selectable is better than what follows:
		if cut_off_selectable_chosen:
			return
				
		if fill_above and focus_widget.selectable():
			# if we're at the top and have a selectable, return
			if self.body.get_prev(fill_above[-1][1]) == (None,None):
				pass #return
				
		# if still none found choose the topmost widget
		good_choices = [j for j in search_order if j not in bad_choices]
		for i in good_choices + search_order:
			row_offset, widget, pos, rows = t[i]
			if pos == focus_pos: continue
			
			# if completely within snap region, adjust row_offset
			if rows + row_offset <= 0:
				snap_rows -= (-row_offset) - (rows-1)
				row_offset = -(rows-1)
				
			self.change_focus( (maxcol,maxrow), pos,
				row_offset, 'below', None,
				snap_rows )
			return
			
		# no choices available, just shift current one
		self.shift_focus((maxcol, maxrow), min(maxrow-1,row_offset))
		
		# final check for pathological case where we may fall short
		middle, top, bottom = self.calculate_visible(
			(maxcol,maxrow), True)
		act_row_offset, _ign1, pos, _ign2, _ign3 = middle
		if act_row_offset >= row_offset:
			# no problem
			return
			
		# fell short, try to select anything else above
		if not t:
			return
		_ign1, _ign2, pos, _ign3 = t[-1]
		widget, pos = self.body.get_prev(pos)
		if widget is None:
			# no dice, we're stuck here
			return
		# bring in only one row if possible
		rows = widget.rows((maxcol,), True)
		self.change_focus((maxcol,maxrow), pos, -(rows-1),
			'below', (self.pref_col, rows-1), 0 )
		
			
		
		
		
		
	def _keypress_page_down(self, size):
		(maxcol, maxrow) = size
		
		middle, top, bottom = self.calculate_visible(
			(maxcol,maxrow), True)
		if middle is None: return 'page down'
			
		row_offset, focus_widget, focus_pos, focus_rows, cursor = middle
		trim_bottom, fill_below = bottom

		# bottom_edge is maxrow-focus_pos rows below top row of focus
		bottom_edge = maxrow - row_offset
		
		# scroll_from_row is (first match)
		# 1. bottom edge if focus is not selectable
		# 2. row containing cursor + 1 if focus has a cursor
		# 3. bottom edge of focus widget if it is visible
		# 4. bottom edge otherwise
		if not focus_widget.selectable():
			scroll_from_row = bottom_edge
		elif cursor is not None:
			x,y = cursor
			scroll_from_row = y + 1
		elif bottom_edge >= focus_rows:
			scroll_from_row = focus_rows
		else:
			scroll_from_row = bottom_edge
		
		# snap_rows is maximum extra rows to scroll when
		# snapping to new a focus
		snap_rows = bottom_edge - scroll_from_row

		# move row_offset to the new desired value (1 "page" down)
		row_offset = -scroll_from_row
		
		# not used below:
		scroll_from_row = bottom_edge = None
		
		
		# gather potential target widgets
		t = []
		# add current focus
		t.append((row_offset,focus_widget,focus_pos,focus_rows))
		pos = focus_pos
		row_offset += focus_rows
		# include widgets from calculate_visible(..)
		for widget, pos, rows in fill_below:
			t.append( (row_offset, widget, pos, rows) )
			row_offset += rows
		# add newly visible ones, including within snap_rows
		snap_region_start = len(t)
		while row_offset < maxrow+snap_rows:
			widget, pos = self.body.get_next(pos)
			if widget is None: break
			rows = widget.rows((maxcol,))
			t.append( (row_offset, widget, pos, rows) ) 
			row_offset += rows
			# determine if one above puts current one into snap rgn
			if row_offset < maxrow:
				snap_region_start += 1
		
		# if we can't fill the bottom we need to adjust the row offsets
		row_offset, w, p, rows = t[-1]
		if row_offset + rows < maxrow:
			adjust = maxrow - (row_offset + rows)
			t = [(ro+adjust, w, p, r) for (ro,w,p,r) in t]	

		# if focus_widget (first in t) is off edge, remove it
		row_offset, w, p, rows = t[0]
		if row_offset+rows <= 0:
			del t[0]
			snap_region_start -= 1

		# we'll need this soon
		self.update_pref_col_from_focus((maxcol,maxrow))
			
		# choose the bottommost selectable and (newly) visible widget
		# search within snap_rows then visible region
		search_order = ( range( snap_region_start, len(t))
				+ range( snap_region_start-1, -1, -1 ) )
		#assert 0, `t, search_order`
		bad_choices = []
		cut_off_selectable_chosen = 0
		for i in search_order:
			row_offset, widget, pos, rows = t[i]
			if not widget.selectable(): 
				continue

			# try selecting this widget
			pref_row = min(maxrow-row_offset-1, rows-1)
			
			# if completely within snap region, adjust row_offset
			if row_offset >= maxrow:
				self.change_focus( (maxcol,maxrow), pos,
					maxrow-1, 'above',
					(self.pref_col, 0),
					snap_rows+maxrow-row_offset-1 )
			else:
				self.change_focus( (maxcol,maxrow), pos,
					row_offset, 'above', 
					(self.pref_col, pref_row), snap_rows )
			
			# find out where that actually puts us
			middle, top, bottom = self.calculate_visible(
				(maxcol,maxrow), True)
			act_row_offset, _ign1, _ign2, _ign3, _ign4 = middle

			# discard chosen widget if it will reduce scroll amount
			# because of a fixed cursor (absolute last resort)
			if act_row_offset < row_offset-snap_rows:
				bad_choices.append(i)
				continue
			if act_row_offset > row_offset:
				bad_choices.append(i)
				continue
			
			# also discard if off top edge (second last resort)
			if act_row_offset+rows > maxrow:
				bad_choices.append(i)
				cut_off_selectable_chosen = 1
				continue
			
			return
			
		# anything selectable is better than what follows:
		if cut_off_selectable_chosen:
			return

		# if still none found choose the bottommost widget
		good_choices = [j for j in search_order if j not in bad_choices]
		for i in good_choices + search_order:
			row_offset, widget, pos, rows = t[i]
			if pos == focus_pos: continue
			
			# if completely within snap region, adjust row_offset
			if row_offset >= maxrow:
				snap_rows -= snap_rows+maxrow-row_offset-1
				row_offset = maxrow-1
				
			self.change_focus( (maxcol,maxrow), pos,
				row_offset, 'above', None,
				snap_rows )
			return
		
			
		# no choices available, just shift current one
		self.shift_focus((maxcol, maxrow), max(1-focus_rows,row_offset))
		
		# final check for pathological case where we may fall short
		middle, top, bottom = self.calculate_visible(
			(maxcol,maxrow), True)
		act_row_offset, _ign1, pos, _ign2, _ign3 = middle
		if act_row_offset <= row_offset:
			# no problem
			return
			
		# fell short, try to select anything else below
		if not t:
			return
		_ign1, _ign2, pos, _ign3 = t[-1]
		widget, pos = self.body.get_next(pos)
		if widget is None:
			# no dice, we're stuck here
			return
		# bring in only one row if possible
		rows = widget.rows((maxcol,), True)
		self.change_focus((maxcol,maxrow), pos, maxrow-1,
			'above', (self.pref_col, 0), 0 )

	def mouse_event(self, size, event, button, col, row, focus):
		"""
		Pass the event to the contained widgets.
		May change focus on button 1 press.
		"""
		(maxcol, maxrow) = size
		middle, top, bottom = self.calculate_visible((maxcol, maxrow),
			focus=True)
		if middle is None:
			return False
		
		_ignore, focus_widget, focus_pos, focus_rows, cursor = middle
		trim_top, fill_above = top
		_ignore, fill_below = bottom

		fill_above.reverse() # fill_above is in bottom-up order
		w_list = ( fill_above + 
			[ (focus_widget, focus_pos, focus_rows) ] +
			fill_below )

		wrow = -trim_top
		for w, w_pos, w_rows in w_list:
			if wrow + w_rows > row:
				break
			wrow += w_rows
		else:
			return False

		focus = focus and w == focus_widget
		if is_mouse_press(event) and button==1:
			if w.selectable():
				self.change_focus((maxcol,maxrow), w_pos, wrow)
		
		if not hasattr(w,'mouse_event'):
			return False

		return w.mouse_event((maxcol,), event, button, col, row-wrow,
			focus)


	def ends_visible(self, size, focus=False):
		"""Return a list that may contain 'top' and/or 'bottom'.
		
		convenience function for checking whether the top and bottom
		of the list are visible
		"""
		(maxcol, maxrow) = size
		l = []
		middle,top,bottom = self.calculate_visible( (maxcol,maxrow), 
			focus=focus )
		trim_top, above = top
		trim_bottom, below = bottom

		if trim_bottom == 0:
			row_offset, w, pos, rows, c = middle
			row_offset += rows
			for w, pos, rows in below:
				row_offset += rows
			if row_offset < maxrow:
				l.append( 'bottom' )
			elif self.body.get_next(pos) == (None,None):
				l.append( 'bottom' )

		if trim_top == 0:
			row_offset, w, pos, rows, c = middle
			for w, pos, rows in above:
				row_offset -= rows
			if self.body.get_prev(pos) == (None,None):
				l.append( 'top' )

		return l



class HListBoxError(Exception):
	pass
	
class HListBox(FlowWidget):
	
	def __init__(self, body):
		"""
		body -- a ListWalker-like object that contains
			widgets to be displayed inside the list box
		"""
		if hasattr(body,'get_focus'):
			self.body = body
		else:
			self.body = PollingListWalker(body)

		try:
			connect_signal(self.body, "modified", self._invalidate)
		except NameError:
			# our list walker has no modified signal so we must not
			# cache our canvases because we don't know when our
			# content has changed
			self.render = nocache_widget_render_instance(self)

		# offset_cols is the number of cols between the left side of
		# the view and the left side of the focused item
		self.offset_cols = 0
		# inset_fraction is used when the focused widget is off the 
		# left side of the view.  it is the fraction of the widget 
		# cut off at the left side.  (numerator, denominator)
		self.inset_fraction = (0,1)

		# pref_col is the preferred column for the cursor when moving
		# between widgets that use the cursor (edit boxes etc.)
		self.pref_col = 'left'

		# variable for delayed focus change used by set_focus
		self.set_focus_pending = 'first selectable'
		
		# variable for delayed align change used by set_focus_align
		self.set_focus_align_pending = None
		
	
	def calculate_visible(self, size, focus=False ):
		""" Return (middle,left,right) or None,None,None.

		middle -- (column offset(when +ve) or inset(when -ve),
			focus widget, focus position, focus cols, 
			cursor coords or None)
		left -- (# columns to trim off left side, 
			list of (widget, position, cols) tuples left
			of the focus in order from right to left)
		right -- (# columns to trim off right side, 
			list of (widget, position, cols) tuples right
			of the focus in order from left to right)
		"""
		maxcol = size[0]
		
		# 0. set the focus if a change is pending
		if self.set_focus_pending or self.set_focus_align_pending:
			self._set_focus_complete(size, focus )

		# 1. start with the focus widget
		focus_widget, focus_pos = self.body.get_focus()
		if focus_widget is None: #list box is empty?
			return None,None,None
		left_pos = right_pos = focus_pos
		focus_size = focus_widget.pack(None, focus)
		
		offset_cols, inset_cols = self.get_focus_offset_inset(size)
		#    force at least one column of focus to be visible
		if offset_cols >= maxcol:
			offset_cols = maxcol -1
		
		#    adjust position so cursor remains visible
		cursor = None
		if focus_widget.selectable() and focus:
			if hasattr(focus_widget,'get_cursor_coords'):
				cursor=focus_widget.get_cursor_coords((maxcol,))
		
		if cursor is not None:
			cx, cy = cursor
			effective_cx = cx + offset_cols - inset_cols
			
			if effective_cx < 0: # cursor past left?
				inset_cols = cx
			elif effective_cx >= maxcol: # cursor past right?
				offset_cols = maxcol - cx -1
		
		#    set trim_top by focus trimmimg
		trim_left = inset_cols
		focus_cols = focus_size[0]
		
		# 2. collect the widgets left of the focus
		pos = focus_pos
		fill_cols = offset_cols
		fill_left = []
		left_pos = pos
		while fill_cols > 0:
			prev, pos = self.body.get_prev( pos )
			if prev is None: # run out of widgets to left?
				offset_cols -= fill_cols
				break
			top_pos = pos
	
			p_cols = prev.pack(None, False)[0]
			fill_left.append( (prev, pos, p_cols) )
			if p_cols > fill_cols: # crosses left edge?
				trim_left = p_cols-fill_cols
				break
			fill_cols -= p_cols
		
		trim_right = focus_cols + offset_cols - inset_cols - maxcol
		if trim_right < 0: trim_right = 0

		# 3. collect the widgets right of the focus
		pos = focus_pos
		fill_cols = maxcol - focus_cols - offset_cols + inset_cols
		fill_right = []
		while fill_cols > 0:
			next, pos = self.body.get_next( pos )
			if next is None: # run out of widgets below?
				break
			right_pos = pos
				
			n_cols = next.pack(None, False)[0]
			fill_right.append( (next, pos, n_cols) )
			if n_cols > fill_cols: # crosses bottom edge?
				trim_right = n_cols-fill_cols
				fill_cols -= n_cols
				break
			fill_cols -= n_cols

		# 4. fill from left again if necessary & possible
		fill_cols = max(0, fill_cols)
		
		if fill_cols >0 and trim_left >0:
			if fill_cols <= trim_left:
				trim_left -= fill_cols
				offset_cols += fill_cols
				fill_cols = 0
			else:
				fill_cols -= trim_left
				offset_cols += trim_left
				trim_left = 0
		pos = left_pos
		while fill_cols > 0:
			prev, pos = self.body.get_prev( pos )
			if prev is None:
				break

			p_cols = prev.pack(None, False)[0]
			fill_left.append( (prev, pos, p_cols) )
			if p_cols > fill_cols: # more than required
				trim_left = p_cols-fill_cols
				offset_cols += fill_cols
				break
			fill_cols -= p_cols
			offset_cols += p_cols
		
		# 5. return the interesting bits
		return ((offset_cols - inset_cols, focus_widget, 
				focus_pos, focus_cols, cursor ),
			(trim_left, fill_left), (trim_right, fill_right))


	def render(self, size, focus=False ):
		"""
		Render listbox and return canvas.
		"""
		(maxcol,) = size

		middle, left, right = self.calculate_visible( (maxcol,), 
			focus=focus)
		if middle is None:
			return SolidCanvas(" ", maxcol, 1)
		
		_ignore, focus_widget, focus_pos, focus_cols, cursor = middle
		trim_left, fill_left = left
		trim_right, fill_right = right

		joinlist = []
		cols = 0
		fill_left.reverse() # fill_above is in rtol order
		for widget,w_pos,w_cols in fill_left:
			canvas = widget.render((w_cols,))
			cols += w_cols
			joinlist.append((canvas, w_pos, False, w_cols))
		
		focus_canvas = focus_widget.render((focus_cols,), focus=focus)

		c_cursor = focus_canvas.cursor
		if cursor != c_cursor:
			raise HListBoxError, "Focus Widget %s at position %s within listbox calculated cursor coords %s but rendered cursor coords %s!" %(`focus_widget`,`focus_pos`,`cursor`,`c_cursor`)
			
		cols += focus_cols
		joinlist.append((focus_canvas, focus_pos, True, focus_cols))
		
		for widget,w_pos,w_cols in fill_below:
			canvas = widget.render((w_cols,))
			cols += w_cols
			joinlist.append((canvas, w_pos, False, w_cols))
		
		final_canvas = CanvasJoin(joinlist)
		
		if trim_left or trim_right:	
			final_canvas.pad_trim_left_right(
				-trim_left, -trim_right)
			cols -= trim_left + trim_right
		
		assert cols <= maxcol, "HListbox contents too long!  Probably urwid's fault (please report): %s" % `left,middle,right`
		
		if cols < maxcol:
			right_pos = focus_pos
			if fill_right: right_pos = fill_right[-1][1]
			assert trim_right==0 and self.body.get_next(right_pos) == (None,None), "HListbox contents too short!  Probably urwid's fault (please report): %s" % `top,middle,bottom`
			final_canvas.pad_trim_left_right(0, maxcol - cols)

		return final_canvas


	def set_focus_align(self, align):
		"""Set the focus widget's display offset and inset.

		align -- one of:
		    'left', 'center', 'right'
		    ('fixed left', columns)
		    ('fixed right', columns)
		    ('relative', percentage 0=left 100=right)
		"""
		vt,va,ht,ha=decompose_valign_height(valign,None,ListBoxError)
		self.set_focus_align_pending = at,aa


	def set_focus(self, position, coming_from=None):
		"""
		Set the focus position and try to keep the old focus in view.

		position -- a position compatible with self.body.set_focus
		coming_from -- set to 'left' or 'right' if you know that
		               old position is left or right of the new 
			       position.
		"""
		assert coming_from in ('left', 'right', None)
		focus_widget, focus_pos = self.body.get_focus()
		
		self.set_focus_pending = coming_from, focus_widget, focus_pos
		self.body.set_focus(position)

	def get_focus(self):
		"""
		Return a (focus widget, focus position) tuple.
		"""
		return self.body.get_focus()

	def _set_focus_align_complete(self, size, focus):
		"""
		Finish setting the offset and inset now that we have have a 
		maxcol & maxrow.
		"""
		at,aa = self.set_focus_align_pending
		self.set_focus_align_pending = None
		self.set_focus_pending = None

		focus_widget, focus_pos = self.body.get_focus()
		if focus_widget is None:
			return
		
		cols = focus_widget.pack(None, focus)
		rleft, rright = calculate_padding( at, aa, 'fixed', cols, 
			None, maxcol )

		self.shift_focus(size, rtop)
	
	def _set_focus_first_selectable(self, size, focus):
		"""
		Choose the first visible, selectable widget below the
		current focus as the focus widget.
		"""
		(maxcol,) = size
		self.set_focus_align_pending = None
		self.set_focus_pending = None
		middle, left, right = self.calculate_visible( 
			(maxcol,), focus=focus)
		if middle is None:
			return
		
		col_offset, focus_widget, focus_pos, focus_rows, cursor = middle
		trim_left, fill_left = top
		trim_right, fill_right = bottom

		if focus_widget.selectable():
			return

		if trim_right:
			fill_right = fill_right[:-1]
		new_col_offset = col_offset + focus_col
		for widget, pos, cols in fill_right:
			if widget.selectable():
				self.body.set_focus(pos)
				self.shift_focus((maxcol,), new_col_offset)
				return
			new_col_offset += cols

	def _set_focus_complete(self, size, focus):
		"""
		Finish setting the position now that we have maxcol.
		"""
		(maxcol,) = size
		self._invalidate()
		if self.set_focus_pending == "first selectable":
			return self._set_focus_first_selectable(
				(maxcol,), focus)
		if self.set_focus_align_pending is not None:
			return self._set_focus_align_complete(
				(maxcol,), focus)
		coming_from, focus_widget, focus_pos = self.set_focus_pending
		self.set_focus_pending = None
		
		# new position
		new_focus_widget, position = self.body.get_focus()
		if focus_pos == position:
			# do nothing
			return
			
		# restore old focus temporarily
		self.body.set_focus(focus_pos)
				
		middle,left,right=self.calculate_visible((maxcol,),focus)
		focus_offset, focus_widget, focus_pos, focus_cols, cursor=middle
		trim_left, fill_left = top
		trim_right, fill_right = bottom
		
		offset = focus_offset
		for widget, pos, cols in fill_left:
			offset -= cols
			if pos == position:
				self.change_focus((maxcol,), pos,
					offset, 'right' )
				return

		offset = focus_offset + focus_cols
		for widget, pos, cols in fill_left:
			if pos == position:
				self.change_focus((maxcol,), pos,
					offset, 'left' )
				return
			offset += cols

		# failed to find widget among visible widgets
		self.body.set_focus( position )
		widget, position = self.body.get_focus()
		cols = widget.pack(None, focus)[0]

		if coming_from=='below':
			offset = 0
		elif coming_from=='above':
			offset = maxcol-cols
		else:
			offset = (maxcol-cols)/2
		self.shift_focus((maxcol,), offset)
	

	def shift_focus(self, size, offset_inset ):
		"""Move the location of the current focus relative to the top.
		
		offset_inset -- either the number of columns between the 
		  left of the HListBox and the start of the focus widget (+ve
		  value) or the number of columns of the focus widget hidden 
		  off the left edge of the HListBox (-ve value) or 0 if the 
		  left edge of the focus widget is aligned with the top edge 
		  of the HListBox
		"""
		(maxcol,) = size
		
		if offset_inset >= 0:
			if offset_inset >= maxcol:
				raise HListBoxError, "Invalid offset_inset: %s, only %s cols in HListBox"% (`offset_inset`, `maxcol`)
			self.offset_cols = offset_inset
			self.inset_fraction = (0,1)
		else:
			target, _ignore = self.body.get_focus()
			tgt_cols = target.pack(None, True)[0]
			if offset_inset + tgt_cols <= 0:
				raise HListBoxError, "Invalid offset_inset: %s, only %s rows in target!" %(`offset_inset`, `tgt_rows`)
			self.offset_cols = 0
			self.inset_fraction = (-offset_inset,tgt_cols)
		self._invalidate()
				
	def update_pref_col_from_focus(self, size):
		"""Update self.pref_col from the focus widget."""
		(maxcol,) = size
		
		widget, old_pos = self.body.get_focus()
		if widget is None: return

		pref_col = None
		wcol = widget.pack(None, True)[0]
		if hasattr(widget,'get_pref_col'):
			pref_col = widget.get_pref_col((wcol,))
		if pref_col is None and hasattr(widget,'get_cursor_coords'):
			coords = widget.get_cursor_coords((wcol,))
			if type(coords) == type(()):
				pref_col,y = coords
		if pref_col is not None: 
			if type(pref_col) == type(0):
				offset, inset = self.get_focus_offset_inset()
				pref_col += offset - inset
			self.pref_col = pref_col


	def change_focus(self, size, position, 
			offset_inset = 0, coming_from = None, 
			cursor_coords = None, snap_cols = None ):
		"""Change the current focus widget.
		
		position -- a position compatible with self.body.set_focus
		offset_inset -- either the number of cols between the 
		  left of the HListBox and the start of the focus widget (+ve
		  value) or the number of columns of the focus widget hidden 
		  off the left edge of the HListBox (-ve value) or 0 if the 
		  left edge of the focus widget is aligned with the left edge 
		  of the HListBox (default if unspecified)
		coming_from -- eiter 'left', 'right' or unspecified (None)
		cursor_coords -- (x, y) tuple indicating the desired
		  column and row for the cursor, or unspecified (None)
		snap_cols -- the maximum number of extra cols to scroll
		  when trying to "snap" a selectable focus into the view
		"""
		(maxcol,) = size
		
		pref_row = None
		if cursor_coords:
			pref_row = cursor_coords[1]

		self._invalidate()
		self.body.set_focus(position)
		target, _ignore = self.body.get_focus()
		tgt_cols = target.pack(None, True)
		if snap_cols is None:
			snap_cols = maxcol-1

		# "snap" to selectable widgets
		align_left = 0
		align_right = maxcol - tgt_cols
		
		if (coming_from == 'left' 
				and target.selectable()
				and offset_inset > align_right
				and align_right >= offset_inset-snap_cols ):
			offset_inset = align_right
			
		if (coming_from == 'below' 
				and target.selectable() 
				and offset_inset < align_left
				and align_left <= offset_inset+snap_cols ):
			offset_inset = align_left
		
		# convert offset_inset to offset_cols or inset_fraction
		if offset_inset >= 0:
			self.offset_cols = offset_inset
			self.inset_fraction = (0,1)
		else:
			if offset_inset + tgt_cols <= 0:
				raise HListBoxError, "Invalid offset_inset: %s, only %s cols in target!" %(offset_inset, tgt_cols)
			self.offset_cols = 0
			self.inset_fraction = (-offset_inset,tgt_cols)
		
		if cursor_coords is None:
			if coming_from is None: 
				return # must either know row or coming_from
		
		if not hasattr(target,'move_cursor_to_coords'):
			return
			
		if cursor_coords is None:
			if coming_from=='left':
				cursor_coords = (0, pref_row)
			else:
				cursor_coords = (tgt_cols-1, pref_row)
		
		target.move_cursor_to_coords((tgt_cols,),cursor_coords[0],
			cursor_coords[1])
	
	def get_focus_offset_inset(self, size):
		"""Return (offset rows, inset rows) for focus widget."""
		(maxcol,) = size
		focus_widget, pos = self.body.get_focus()
		focus_cols = focus_widget.pack(None, True)[0]
		offset_cols = self.offset_cols
		inset_cols = 0
		if offset_cols == 0:
			inum, iden = self.inset_fraction
			if inum < 0 or iden < 0 or inum >= iden:
				raise HListBoxError, "Invalid inset_fraction: %s"%`self.inset_fraction`
			inset_cols = focus_cols * inum / iden
			assert inset_cols < focus_cols, "urwid inset_fraction error (please report)"
		return offset_cols, inset_cols


	def make_cursor_visible(self, size):
		"""Shift the focus widget so that its cursor is visible."""
		(maxcol,) = size
		
		focus_widget, pos = self.body.get_focus()
		if focus_widget is None:
			return
		if not focus_widget.selectable(): 
			return
		if not hasattr(focus_widget,'get_cursor_coords'): 
			return
		mc = focus_widget.pack(None, True)[0]
		cursor = focus_widget.get_cursor_coords((mc,))
		if cursor is None: 
			return
		cx, cy = cursor
		offset_cols, inset_cols = self.get_focus_offset_inset(
			(maxcol,))
		
		if cx < inset_cols:
			self.shift_focus((maxcol,), - (cx) )
			return
			
		if offset_cols - inset_cols + cx >= maxcol:
			self.shift_focus( (maxcol,), maxcol-cx-1 )
			return


