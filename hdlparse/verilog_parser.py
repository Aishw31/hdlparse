# -*- coding: utf-8 -*-
# Copyright © 2017 Kevin Thibedeau
# Distributed under the terms of the MIT license
from __future__ import print_function

import re, os, io, ast, pprint, collections
from .minilexer import MiniLexer

'''Verilog documentation parser'''

verilog_tokens = {
  'root': [
    (r'\bmodule\s+(\w+)\s*', 'module', 'module'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'//#+(.*)\n', 'metacomment'),
    (r'//.*\n', None),
  ],
  'module': [
    (r'parameter\s*(signed|integer|realtime|real|time)?\s*(\[[^]]+\])?', 'parameter_start', 'parameters'),
    (r'(input|inout|output)\s*(reg|supply0|supply1|tri|triand|trior|tri0|tri1|wire|wand|wor)?\s*(signed)?\s*(\[[^]]+\])?', 'module_port_start', 'module_port'),
    (r'endmodule', 'end_module', '#pop'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'//#\s*{{(.*)}}\n', 'section_meta'),
    (r'//.*\n', None),
  ],
  'parameters': [
    (r'\s*parameter\s*(signed|integer|realtime|real|time)?\s*(\[[^]]+\])?', 'parameter_start'),
    (r'\s*(\w+)[^),;]*', 'param_item'),
    (r',', None),
    (r'[);]', None, '#pop'),
  ],
  'module_port': [
    (r'\s*(input|inout|output)\s*(reg|supply0|supply1|tri|triand|trior|tri0|tri1|wire|wand|wor)?\s*(signed)?\s*(\[[^]]+\])?', 'module_port_start'),
    (r'\s*(\w+)\s*,?', 'port_param'),
    (r'[);]', None, '#pop'),
    (r'//#\s*{{(.*)}}\n', 'section_meta'),
    (r'//.*\n', None),
  ],

  'block_comment': [
    (r'\*/', 'end_comment', '#pop'),
  ],
}


VerilogLexer = MiniLexer(verilog_tokens)

class VerilogObject(object):
  '''Base class for parsed Verilog objects'''
  def __init__(self, name, desc=None):
    self.name = name
    self.kind = 'unknown'
    self.desc = desc

class VerilogParameter(object):
  '''Parameter and port to a module'''
  def __init__(self, name, mode=None, data_type=None, default_value=None, desc=None):
    self.name = name
    self.mode = mode
    self.data_type = data_type
    self.default_value = default_value
    self.desc = desc

  def __str__(self):
    if self.mode is not None:
      param = '{} : {} {}'.format(self.name, self.mode, self.data_type)
    else:
      param = '{} : {}'.format(self.name, self.data_type)
    if self.default_value is not None:
      param = '{} := {}'.format(param, self.default_value)
    return param
      
  def __repr__(self):
    return "VerilogParameter('{}')".format(self.name)

class VerilogModule(VerilogObject):
  '''Module definition'''
  def __init__(self, name, ports, generics=None, sections=None, desc=None):
    VerilogObject.__init__(self, name, desc)
    self.kind = 'module'
    # Verilog params
    self.generics = generics if generics is not None else []
    self.ports = ports
    self.sections = sections if sections is not None else {}
  def __repr__(self):
    return "VerilogModule('{}') {}".format(self.name, self.ports)



def parse_verilog_file(fname):
  '''Parse a named Verilog file
  
  Args:
    fname (str): File to parse.
  Returns:
    List of parsed objects.
  '''
  with open(fname, 'rt') as fh:
    text = fh.read()
  return parse_verilog(text)

def parse_verilog(text):
  '''Parse a text buffer of Verilog code

  Args:
    text (str): Source code to parse
  Returns:
    List of parsed objects.
  '''
  lex = VerilogLexer

  name = None
  kind = None
  saved_type = None
  mode = 'input'
  ptype = 'wire'

  metacomments = []
  parameters = []
  param_items = []

  generics = []
  ports = collections.OrderedDict()
  sections = []
  port_param_index = 0
  last_item = None
  array_range_start_pos = 0

  objects = []

  for pos, action, groups in lex.run(text):
    if action == 'metacomment':
      if last_item is None:
        metacomments.append(groups[0])
      else:
        last_item.desc = groups[0]

    if action == 'section_meta':
      sections.append((port_param_index, groups[0]))

    elif action == 'module':
      kind = 'module'
      name = groups[0]
      generics = []
      ports = collections.OrderedDict()
      param_items = []
      sections = []
      port_param_index = 0

    elif action == 'parameter_start':
      net_type, vec_range = groups

      new_ptype = ''
      if net_type is not None:
        new_ptype += net_type

      if vec_range is not None:
        new_ptype += ' ' + vec_range

      ptype = new_ptype

    elif action == 'param_item':
      generics.append(VerilogParameter(groups[0], 'in', ptype))

    elif action == 'module_port_start':
      new_mode, net_type, signed, vec_range = groups

      new_ptype = ''
      if net_type is not None:
        new_ptype += net_type

      if signed is not None:
        new_ptype += ' ' + signed

      if vec_range is not None:
        new_ptype += ' ' + vec_range

      # Complete pending items
      for i in param_items:
        ports[i] = VerilogParameter(i, mode, ptype)

      param_items = []
      if len(ports) > 0:
        last_item = next(reversed(ports))

      # Start with new mode
      mode = new_mode
      ptype = new_ptype

    elif action == 'port_param':
      ident = groups[0]

      param_items.append(ident)
      port_param_index += 1

    elif action == 'end_module':
      # Finish any pending ports
      for i in param_items:
        ports[i] = VerilogParameter(i, mode, ptype)

      vobj = VerilogModule(name, ports.values(), generics, dict(sections), metacomments)
      objects.append(vobj)
      last_item = None
      metacomments = []

  return objects


def is_verilog(fname):
  '''Identify file as Verilog by its extension
  
  Args:
    fname (str): File name to check
  Returns:
    True when file has a Verilog extension.
  '''
  return os.path.splitext(fname)[1].lower() in ('.vlog', '.v')


class VerilogExtractor(object):
  '''Utility class that caches parsed objects'''
  def __init__(self):
    self.object_cache = {}

  def extract_objects(self, fname, type_filter=None):
    '''Extract objects from a source file

    Args:
      fname(str): Name of file to read from
      type_filter (class, optional): Object class to filter results
    Returns:
      List of objects extracted from the file.
    '''
    objects = []
    if fname in self.object_cache:
      objects = self.object_cache[fname]
    else:
      with io.open(fname, 'rt', encoding='utf-8') as fh:
        text = fh.read()
        objects = parse_verilog(text)
        self.object_cache[fname] = objects

    if type_filter:
      objects = [o for o in objects if isinstance(o, type_filter)]

    return objects


  def extract_objects_from_source(self, text, type_filter=None):
    '''Extract object declarations from a text buffer

    Args:
      text (str): Source code to parse
      type_filter (class, optional): Object class to filter results
    Returns:
      List of parsed objects.
    '''
    objects = parse_verilog(text)

    if type_filter:
      objects = [o for o in objects if isinstance(o, type_filter)]

    return objects


  def is_array(self, data_type):
    '''Check if a type is an array type
    
    Args:
      data_type (str): Data type
    Returns:
      True when a data type is an array.
    '''
    return '[' in data_type

