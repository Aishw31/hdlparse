# -*- coding: utf-8 -*-
# Copyright © 2017 Kevin Thibedeau
# Distributed under the terms of the MIT license
from __future__ import print_function

import re, os, io, ast
from pprint import pprint
from .minilexer import MiniLexer

'''VHDL documentation parser'''

vhdl_tokens = {
  'root': [
    (r'package\s+(\w+)\s+is', 'package', 'package'),
    (r'package\s+body\s+(\w+)\s+is', 'package_body', 'package_body'),
    (r'function\s+(\w+|"[^"]+")\s*\(', 'function', 'param_list'),
    (r'procedure\s+(\w+)\s*\(', 'procedure', 'param_list'),
    (r'function\s+(\w+)', 'function', 'simple_func'),
    (r'component\s+(\w+)\s*is', 'component', 'component'),
    (r'entity\s+(\w+)\s*is', 'entity', 'entity'),
    (r'architecture\s+(\w+)\s*of', 'architecture', 'architecture'),
    (r'subtype\s+(\w+)\s+is\s+(\w+)', 'subtype'),
    (r'type\s+(\w+)\s*is', 'type', 'type_decl'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'package': [
    (r'function\s+(\w+|"[^"]+")\s*\(', 'function', 'param_list'),
    (r'procedure\s+(\w+)\s*\(', 'procedure', 'param_list'),
    (r'function\s+(\w+)', 'function', 'simple_func'),
    (r'component\s+(\w+)\s*is', 'component', 'component'),
    (r'subtype\s+(\w+)\s+is\s+(\w+)', 'subtype'),
    (r'constant\s+(\w+)\s+:\s+(\w+)', 'constant'),
    (r'type\s+(\w+)\s*is', 'type', 'type_decl'),
    (r'end\s+package', None, '#pop'),
    (r'--#(.*)\n', 'metacomment'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'package_body': [
    (r'end\s+package\s+body', None, '#pop'),
    (r'--#(.*)\n', 'metacomment'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'type_decl': [
    (r'array', 'array_type', '#pop'),
    (r'file', 'file_type', '#pop'),
    (r'access', 'access_type', '#pop'),
    (r'record', 'record_type', '#pop'),
    (r'range', 'range_type', '#pop'),
    (r'\(', 'enum_type', '#pop'),
    (r';', 'incomplete_type', '#pop'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'param_list': [
    (r'\s*((?:variable|signal|constant|file)\s+)?(\w+)\s*', 'param'),
    (r'\s*,\s*', None),
    (r'\s*:\s*', None, 'param_type'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'param_type': [
    (r'\s*((?:in|out|inout|buffer)\s+)?(\w+)\s*', 'param_type'),
    (r'\s*;\s*', None, '#pop'),
    (r"\s*:=\s*('.'|[^\s;)]+)", 'param_default'),
    (r'\)\s*(?:return\s+(\w+)\s*)?;', 'end_subprogram', '#pop:2'),
    (r'\)\s*(?:return\s+(\w+)\s*)?is', None, '#pop:2'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'simple_func': [
    (r'\s+return\s+(\w+)\s*;', 'end_subprogram', '#pop'),
    (r'\s+return\s+(\w+)\s+is', None, '#pop'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'component': [
    (r'generic\s*\(', None, 'generic_list'),
    (r'port\s*\(', None, 'port_list'),
    (r'end\s+component\s*\w*;', 'end_component', '#pop'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'entity': [
    (r'end\s+entity\s*;', 'end_entity', '#pop'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'architecture': [
    (r'end\s+architecture\s*;', 'end_arch', '#pop'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'generic_list': [
    (r'\s*(\w+)\s*', 'generic_param'),
    (r'\s*,\s*', None),
    (r'\s*:\s*', None, 'generic_param_type'),
    (r'--#(.*)\n', 'metacomment'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'generic_param_type': [
    (r'\s*(\w+)\s*', 'generic_param_type'),
    (r'\s*;\s*', None, '#pop'),
    (r"\s*:=\s*([\w']+)", 'generic_param_default'),
    (r'\)\s*;', 'end_generic', '#pop:2'),
    (r'--#(.*)\n', 'metacomment'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'port_list': [
    (r'\s*(\w+)\s*', 'port_param'),
    (r'\s*,\s*', None),
    (r'\s*:\s*', None, 'port_param_type'),
    (r'--#\s*{{(.*)}}\n', 'section_meta'),
    (r'--#(.*)\n', 'metacomment'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'port_param_type': [
    (r'\s*(in|out|inout|buffer)\s+(\w+)\s*\(', 'port_array_param_type', 'array_range'),
    (r'\s*(in|out|inout|buffer)\s+(\w+)\s*', 'port_param_type'),
    (r'\s*;\s*', None, '#pop'),
    (r"\s*:=\s*([\w']+)", 'port_param_default'),
    (r'\)\s*;', 'end_port', '#pop:2'),
    (r'--#(.*)\n', 'metacomment'),
    (r'/\*', 'block_comment', 'block_comment'),
    (r'--.*\n', None),
  ],
  'array_range': [
    (r'\(', 'open_paren', 'nested_parens'),
    (r'\)', 'array_range_end', '#pop'),
  ],
  'nested_parens': [
    (r'\(', 'open_paren', 'nested_parens'),
    (r'\)', 'close_paren', '#pop'),
  ],
  'block_comment': [
    (r'\*/', 'end_comment', '#pop'),
  ],
}
      
VhdlLexer = MiniLexer(vhdl_tokens, flags=re.MULTILINE | re.IGNORECASE)


class VhdlObject(object):
  '''Base class for parsed VHDL objects

  Args:
    name (str): Name of the object
    desc (str): Description from object metacomments
  '''
  def __init__(self, name, desc=None):
    self.name = name
    self.kind = 'unknown'
    self.desc = desc

class VhdlParameter(object):
  '''Parameter to subprograms, ports, and generics
  
  Args:
    name (str): Name of the object
    mode (str): Direction mode for the parameter
    data_type (str): Type name for the parameter
    default_value (str): Default value of the parameter
    desc (str): Description from object metacomments
  '''
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
    return "VhdlParameter('{}', '{}', '{}')".format(self.name, self.mode, self.data_type)

class VhdlPackage(VhdlObject):
  '''Package declaration

  Args:
    name (str): Name of the package
    desc (str): Description from object metacomments
  '''
  def __init__(self, name, desc=None):
    VhdlObject.__init__(self, name, desc)
    self.kind = 'package'

class VhdlType(VhdlObject):
  '''Type definition

  Args:  
    name (str): Name of the type
    package (str): Package containing the type
    type_of (str): Object type of this type definition
    desc (str, optional): Description from object metacomments
  '''
  def __init__(self, name, package, type_of, desc=None):
    VhdlObject.__init__(self, name, desc)
    self.kind = 'type'
    self.package = package
    self.type_of = type_of
  def __repr__(self):
    return "VhdlType('{}', '{}')".format(self.name, self.type_of)


class VhdlSubtype(VhdlObject):
  '''Subtype definition
  
  Args:
    name (str): Name of the subtype
    package (str): Package containing the subtype
    base_type (str): Base type name derived from
    desc (str, optional): Description from object metacomments
  '''
  def __init__(self, name, package, base_type, desc=None):
    VhdlObject.__init__(self, name, desc)
    self.kind = 'subtype'
    self.package = package
    self.base_type = base_type
  def __repr__(self):
    return "VhdlSubtype('{}', '{}')".format(self.name, self.base_type)


class VhdlConstant(VhdlObject):
  '''Constant definition
  
  Args:
    name (str): Name of the constant
    package (str): Package containing the constant
    base_type (str): Type fo the constant
    desc (str, optional): Description from object metacomments
  '''
  def __init__(self, name, package, base_type, desc=None):
    VhdlObject.__init__(self, name, desc)
    self.kind = 'constant'
    self.package = package
    self.base_type = base_type
  def __repr__(self):
    return "VhdlConstant('{}', '{}')".format(self.name, self.base_type)


class VhdlFunction(VhdlObject):
  '''Function declaration
  
  Args:
    name (str): Name of the function
    package (str): Package containing the function
    parameters (list of VhdlParameter): Parameters to the function
    return_type (str, optional): Type of the return value
    desc (str, optional): Description from object metacomments
  '''
  def __init__(self, name, package, parameters, return_type=None, desc=None):
    VhdlObject.__init__(self, name, desc)
    self.kind = 'function'
    self.package = package
    self.parameters = parameters
    self.return_type = return_type

  def __repr__(self):
    return "VhdlFunction('{}')".format(self.name)


class VhdlProcedure(VhdlObject):
  '''Procedure declaration

  Args:
    name (str): Name of the procedure
    package (str): Package containing the procedure
    parameters (list of VhdlParameter): Parameters to the procedure
    desc (str, optional): Description from object metacomments
  '''
  def __init__(self, name, package, parameters, desc=None):
    VhdlObject.__init__(self, name, desc)
    self.kind = 'procedure'
    self.package = package
    self.parameters = parameters

  def __repr__(self):
    return "VhdlProcedure('{}')".format(self.name)


class VhdlComponent(VhdlObject):
  '''Component declaration
  
  Args:
    name (str): Name of the component
    package (str): Package containing the component
    ports (list of VhdlParameter): Port parameters to the component
    generics (list of VhdlParameter): Generic parameters to the component
    sections (list of str): Metacomment sections
    desc (str, optional): Description from object metacomments
  '''
  def __init__(self, name, package, ports, generics=None, sections=None, desc=None):
    VhdlObject.__init__(self, name, desc)
    self.kind = 'component'
    self.package = package
    self.generics = generics if generics is not None else []
    self.ports = ports
    self.sections = sections if sections is not None else {}

  def __repr__(self):
    return "VhdlComponent('{}')".format(self.name)

  def dump(self):
    print('VHDL component: {}'.format(self.name))
    for p in self.ports:
      print('\t{} ({}), {} ({})'.format(p.name, type(p.name), p.data_type, type(p.data_type)))


def parse_vhdl_file(fname):
  '''Parse a named VHDL file
  
  Args:
    fname(str): Name of file to parse
  Returns:
    Parsed objects.
  '''
  with open(fname, 'rt') as fh:
    text = fh.read()
  return parse_vhdl(text)

def parse_vhdl(text):
  '''Parse a text buffer of VHDL code

  Args:
    text(str): Source code to parse
  Returns:
    Parsed objects.
  '''
  lex = VhdlLexer
  
  name = None
  kind = None
  saved_type = None
  end_param_group = False
  cur_package = None

  metacomments = []
  parameters = []
  param_items = []

  generics = []
  ports = []
  sections = []
  port_param_index = 0
  last_item = None
  array_range_start_pos = 0

  objects = []
  
  for pos, action, groups in lex.run(text):
    if action == 'metacomment':
      realigned = re.sub(r'^#+', lambda m: ' ' * len(m.group(0)), groups[0])
      if last_item is None:
        metacomments.append(realigned)
      else:
        last_item.desc = realigned
    if action == 'section_meta':
      sections.append((port_param_index, groups[0]))

    elif action == 'function':
      kind = 'function'
      name = groups[0]
      param_items = []
      parameters = []
    elif action == 'procedure':
      kind = 'procedure'
      name = groups[0]
      param_items = []
      parameters = []
    elif action == 'param':
      if end_param_group:
        # Complete previous parameters
        for i in param_items:
          parameters.append(i)
        param_items = []
        end_param_group = False

      param_items.append(VhdlParameter(groups[1]))
    elif action == 'param_type':
      mode, ptype = groups
      
      if mode is not None:
        mode = mode.strip()
      
      for i in param_items: # Set mode and type for all pending parameters
        i.mode = mode
        i.data_type = ptype

      end_param_group = True

    elif action == 'param_default':
      for i in param_items:
        i.default_value = groups[0]

    elif action == 'end_subprogram':
      # Complete last parameters
      for i in param_items:
        parameters.append(i)
        
      if kind == 'function':
        vobj = VhdlFunction(name, cur_package, parameters, groups[0], metacomments)
      else:
        vobj = VhdlProcedure(name, cur_package, parameters, metacomments)
      
      objects.append(vobj)
    
      metacomments = []
      parameters = []
      param_items = []
      kind = None
      name = None

    elif action == 'component':
      kind = 'component'
      name = groups[0]
      generics = []
      ports = []
      param_items = []
      sections = []
      port_param_index = 0

    elif action == 'generic_param':
      param_items.append(groups[0])

    elif action == 'generic_param_type':
      ptype = groups[0]
      
      for i in param_items:
        generics.append(VhdlParameter(i, 'in', ptype))
      param_items = []
      last_item = generics[-1]

    elif action == 'port_param':
      param_items.append(groups[0])
      port_param_index += 1

    elif action == 'port_param_type':
      mode, ptype = groups

      for i in param_items:
        ports.append(VhdlParameter(i, mode, ptype))

      param_items = []
      last_item = ports[-1]

    elif action == 'port_array_param_type':
      mode, ptype = groups
      array_range_start_pos = pos[1]

    elif action == 'array_range_end':
      arange = text[array_range_start_pos:pos[0]+1]

      for i in param_items:
        ports.append(VhdlParameter(i, mode, ptype + arange))

      param_items = []
      last_item = ports[-1]

    elif action == 'end_component':
      vobj = VhdlComponent(name, cur_package, ports, generics, dict(sections), metacomments)
      objects.append(vobj)
      last_item = None
      metacomments = []

    elif action == 'package':
      objects.append(VhdlPackage(groups[0]))
      cur_package = groups[0]
      kind = None
      name = None

    elif action == 'type':
      saved_type = groups[0]

    elif action in ('array_type', 'file_type', 'access_type', 'record_type', 'range_type', 'enum_type', 'incomplete_type'):
      vobj = VhdlType(saved_type, cur_package, action, metacomments)
      objects.append(vobj)
      kind = None
      name = None
      metacomments = []

    elif action == 'subtype':
      vobj = VhdlSubtype(groups[0], cur_package, groups[1], metacomments)
      objects.append(vobj)
      kind = None
      name = None
      metacomments = []

    elif action == 'constant':
      vobj = VhdlConstant(groups[0], cur_package, groups[1], metacomments)
      objects.append(vobj)
      kind = None
      name = None
      metacomments = []

  return objects


def subprogram_prototype(vo):
  '''Generate a canonical prototype string
  
  Args:
    vo (VhdlFunction, VhdlProcedure): Subprogram object
  Returns:
    Prototype string.
  '''

  plist = '; '.join(str(p) for p in vo.parameters)

  if isinstance(vo, VhdlFunction):
    if len(vo.parameters) > 0:
      proto = 'function {}({}) return {};'.format(vo.name, plist, vo.return_type)
    else:
      proto = 'function {} return {};'.format(vo.name, vo.return_type)

  else: # procedure
    proto = 'procedure {}({});'.format(vo.name, plist)

  return proto

def subprogram_signature(vo, fullname=None):
  '''Generate a signature string
  
  Args:
    vo (VhdlFunction, VhdlProcedure): Subprogram object
  Returns:
    Signature string.
  '''

  if fullname is None:
    fullname = vo.name

  if isinstance(vo, VhdlFunction):
    plist = ','.join(p.data_type for p in vo.parameters)
    sig = '{}[{} return {}]'.format(fullname, plist, vo.return_type)
  else: # procedure
    plist = ','.join(p.data_type for p in vo.parameters)
    sig = '{}[{}]'.format(fullname, plist)

  return sig


def is_vhdl(fname):
  '''Identify file as VHDL by its extension
  
  Args:
    fname (str): File name to check
  Returns:
    True when file has a VHDL extension.
  '''
  return os.path.splitext(fname)[1].lower() in ('.vhdl', '.vhd')


class VhdlExtractor(object):
  '''Utility class that caches parsed objects and tracks array type definitions

  Args:
    array_types(set): Initial array types
  '''
  def __init__(self, array_types=set()):
    self.array_types = set(('std_ulogic_vector', 'std_logic_vector',
      'signed', 'unsigned', 'bit_vector'))

    self.array_types |= array_types
    self.object_cache = {}

  def extract_objects(self, fname, type_filter=None):
    '''Extract objects from a source file
    
    Args:
      fname (str): File to parse
      type_filter (class, optional): Object class to filter results
    Returns:
      List of parsed objects.
    '''
    objects = []
    if fname in self.object_cache:
      objects = self.object_cache[fname]
    else:
      with io.open(fname, 'rt', encoding='latin-1') as fh:
        text = fh.read()
        objects = parse_vhdl(text)
        self.object_cache[fname] = objects
        self._register_array_types(objects)

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
    objects = parse_vhdl(text)
    self._register_array_types(objects)

    if type_filter:
      objects = [o for o in objects if isinstance(o, type_filter)]

    return objects


  def is_array(self, data_type):
    '''Check if a type is a known array type
    
    Args:
      data_type (str): Name of type to check
    Returns:
      True if ``data_type`` is a known array type.
    '''

    # Split off any brackets
    data_type = data_type.split('[')[0].strip()

    return data_type.lower() in self.array_types


  def _add_array_types(self, type_defs):
    '''Add array data types to internal registry
    
    Args:
      type_defs (dict): Dictionary of type definitions
    '''
    if 'arrays' in type_defs:
      self.array_types |= set(type_defs['arrays'])

  def load_array_types(self, fname):
    '''Load file of previously extracted data types
    
    Args:
      fname (str): Name of file to load array database from
    '''
    type_defs = ''
    with open(fname, 'rt') as fh:
      type_defs = fh.read()

    try:
      type_defs = ast.literal_eval(type_defs)
    except SyntaxError:
      type_defs = {}

    self._add_array_types(type_defs)

  def save_array_types(self, fname):
    '''Save array type registry to a file
    
    Args:
      fname (str): Name of file to save array database to
    '''
    type_defs = {'arrays': sorted(list(self.array_types))}
    with open(fname, 'wt') as fh:
      pprint(type_defs, stream=fh)

  def _register_array_types(self, objects):
    '''Add array type definitions to internal registry
    
    Args:
      objects (list of VhdlType or VhdlSubtype): Array types to track
    '''
    # Add all array types directly
    types = [o for o in objects if isinstance(o, VhdlType) and o.type_of == 'array_type']
    for t in types:
      self.array_types.add(t.name)

    subtypes = {o.name:o.base_type for o in objects if isinstance(o, VhdlSubtype)}

    # Find all subtypes of an array type
    for k,v in subtypes.iteritems():
      while v in subtypes: # Follow subtypes of subtypes
        v = subtypes[v]
      if v in self.array_types:
        self.array_types.add(k)

  def register_array_types_from_sources(self, source_files):
    '''Add array type definitions from a file list to internal registry

    Args:
      source_files (list of str): Files to parse for array definitions
    '''
    for fname in source_files:
      if is_vhdl(fname):
        self._register_array_types(self.extract_objects(fname))


if __name__ == '__main__':
  ve = VhdlExtractor()
  code = '''
package foo is
  function afunc(q,w,e : std_ulogic; h,j,k : unsigned) return std_ulogic;

  procedure aproc( r,t,y : in std_ulogic; u,i,o : out signed);

  component acomp is
    port (
      a,b,c : in std_ulogic;
      f,g,h : inout bit
    );
  end component;

end package;
  '''

  objs = ve.extract_objects_from_source(code)

  for o in objs:
    print(o.name)
    try:
      for p in o.parameters:
        print(p)
    except:
      pass

    try:
      for p in o.ports:
        print(p)
    except:
      pass
