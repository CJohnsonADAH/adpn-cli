#!/usr/bin/python3
#
# adpn-json.py: utility script for handling JSON data in Python or in shell
# The script pulls data elements from a JSON hash table provided on stdin and
# then outputs the value (a printed str, a serialized str equivalent or new JSON)
# from a key-value pair, so that scripts can capture and manipulate values in JSON packets.
#
# @version 2021.0811

import sys
import os.path
import fileinput
import re, json, codecs
import urllib.parse
from myLockssScripts import myPyCommandLine, myPyJSON
from ADPNCommandLineTool import ADPNCommandLineTool


class ADPNDataConverter :
    def __init__ (self, data, mime="text/tab-separated-values") :
        self.data = data
        self.output = []
        self.mime = mime
    
    @property
    def data (self) :
        return self._data
    
    @data.setter
    def data (self, rhs) :
        self._data = rhs
    
    @property
    def mime (self) -> str:
        return self._mime
        
    @mime.setter
    def mime (self, rhs: str) : 
        assert type(rhs) is str, "MIME type must be a str"
        
        mime_type = rhs
        mime_parameters = []
        
        m = re.match(r'^([^;]+)[;]\s*(.*)\s*$', rhs)
        if m :
            mime_type = m.group(1)
            mime_parameters = re.split(r'\s*[;]\s*', m.group(2))
            
        self._mime = mime_type
        self._mime_parameters = mime_parameters
    
    @property
    def output (self) -> list :
        return self._output
    
    @output.setter
    def output (self, rhs: list) :
        assert all([ type(item) is str for item in rhs ]), "Output lines must be type str"
        self._output = [ item for item in rhs ]
    
    def add_output (self, lines) :
        if type(lines) is str :
            to_add = [ lines ]
        elif type(lines) is list :
            to_add = [ line for line in lines ]
        else :
            raise TypeError("argument lines must be a str or a list of str")
        assert all([ type(item) is str for item in to_add ]), "argument lines must be a str or a list of str"
        
        self._output.extend(lines)
    
    def write_output (self, template=None, where=None, delimiter="\n", end=None, file=sys.stdout) :
        ok = ( ( lambda x: True ) if where is None else where )
        tmpl = ( ( lambda s: s ) if template is None else template )
        assert callable(ok), "parameter @where must be a callable filter function, for example where=lambda s: len(s) > 0"
        assert callable(tmpl), "parameter @template must be a callable filter function, for example template=lambda s: s.strip()"
        
        fmt=[ tmpl(line) for line in self.output if ok(line) ]
        if len(fmt) > 0 :
            print(delimiter.join(fmt), end=end, file=file)
    
    def wants_table_output (self) :
        return False # DBG
        
    def wants_json_table_output (self) :
        return ( self.wants_json_output() and self.wants_table_output() )
        
    def wants_json_output (self) :
        return ( self.get_output_format() in [ 'json', 'application/json' ] )
    
    def wants_urlencoded_output (self) :
        return ( self.get_output_format() in [ 'urlencode', 'multipart/form-data' ] )
    
    def get_output_format (self) :
        return self.mime

class ADPNDataList(ADPNDataConverter) :
    
    def __init__ (self, data, mime="text/tab-separated-values") :
        # raises TypeError if data is not iterable
        _ = (e for e in data)
        
        # str is iterable, but we do not want it treated like a list of characters
        assert not ( type(data) is str ), "ADPNDataList parameter @data must be an iterable data object that is not a str"
        
        super().__init__(data, mime)
    
    def convertto_text (self) :
        self.output.extend( [ self.format_output(line) for line in self.data ] )
    
    def format_output (self, item) :
        if self.mime is None :
            output = item
        elif self.wants_json_output() :
            output = json.dumps(item)
        elif self.wants_urlencoded_output() :
            output = str(item)
            output = urllib.parse.quote(output.encode("utf-8", "surrogatepass"))
        else :
            output = item
        return output
    
class ADPNDataTable(ADPNDataConverter) :
    def __init__ (self, data, mime='text/tab-separated-values') :
        try :
            if type(data) is list :
                for row in data :
                    _ = ( col for col in row )
            else :
                _ = ( (k, v) for (k, v) in data.items() )
        except TypeError as e :
            raise TypeError("ADPNDataList parameter @data must be a type that can be processed as a data table, for example a dict or list of lists") from e
        except AttributeError as e :
            raise TypeError("ADPNDataList parameter @data must be a type that can be processed as a data table, for example a dict or list of lists") from e
        
        super().__init__(data, mime)
    
    @property
    def data_rows (self) :
        try :
            rows = [ (k, v) for (k, v) in self.data.items() ]
        except AttributeError as e :
            rows = [ row for row in self.data ]
        return rows
        
    def convertto_text (self) :
        self.output.extend( [ self.format_output(row) for row in self.data_rows ] )
    
    def format_output (self, item) :
        if self.mime is None :
            output = item
        elif self.wants_json_output() :
            output = json.dumps(item)
        elif self.wants_urlencoded_output() :
            output = "\t".join([ urllib.parse.quote(col.encode("utf-8", "surrogatepass")) for col in item ])
        else :
            output = "\t".join(item)
        return output
    
class ADPNGetJSON(ADPNCommandLineTool) :
    """
Usage: VALUE=$( <INPUT> | adpn-json.py - --key=<KEY> )

Input: a copy-pasted block of text, including one or more JSON hash tables,
possibly prefixed by a label like "JSON PACKET: " before the beginning of
the {...} hash table structure. (The label will be ignored.) If there are
multiple lines with JSON hash tables in them, the divers hash tables will
be merged together into one big hash table.

Output: the str value or typecasted str serialization of the value paired
with the provided key in the hash table. If there is no such key in the
hash table, nothing is printed out.

Exit code:
0= successful output of the value associated with the key requested
1= failed to output a value because the key requested does not exist
2= failed to output a value because the JSON could not be decoded
    """

    def __init__ (self, scriptpath, argv, switches, scriptname=None) :
        super().__init__(scriptpath, argv, switches, scriptname)
        
        self._output = []
        self._flags = { "json_error": [], "key_error": [], "nothing_found": [], "output_error": [] }
        self._default_mime = "text/plain"
        self._json = None
        
    @property
    def flags (self) :
        return self._flags

    @property
    def output (self) :
        return self._output
    
    @property
    def exitcode (self) -> int :
        if self.test_flagged("json_error") :
            self._exitcode=2
        elif self.test_flagged("key_error") :
            self._exitcode=1
        elif self.test_flagged("output_error") :
            self._exitcode=254
        else :
            self._exitcode=0
        return super().exitcode
    
    @exitcode.setter
    def exitcode (self, code: int) :
        super().set_exitcode(code)
        
    def add_flag (self, flag, value) :
        if value is not None :
            self.flags[flag].extend( [ value ] )

    def test_flagged (self, flag) :
        flags = self.flags[flag]
        return (len(flags) > 0)	

    def wants_splat(self) :
        return ( self.switches.get('nosplat') is None )

    def wants_cascade(self) :
        return ( self.switches.get('cascade') is not None )
        
    def wants_table(self) :
        requested_table = (( self.get_output_format(index=0) == "text/tab-separated-values" ) or ( self.get_output_format(index=1) == "table" ))
        implies_table = (( self.switches.get('key') is None ) and ( self.get_output_format(index=0) is None )) 
        return implies_table or requested_table

    def wants_printf_output (self) :
        return (( self.get_output_format() == "text/plain" ) and ( self.switches.get('template') is not None ))

    def wants_json_output(self) :
        return (( self.get_output_format() == "json" ) or ( self.get_output_format() == "application/json" ) )
        
    def data_matches (self, item, key, value) :
        matched = True
        if isinstance(item, dict) :
            matched = False
            m=re.match(r"^[/](.*)[/]$", value)
            if m :
                match_re = ( re.match(m[1], item.get(key) ) )
                matched = not not match_re
            elif isinstance(item.get(key), str ) :
                matched = ( item.get(key) == str(value) )
            elif isinstance(item.get(key), int ) :
                matched = ( item.get(key) == int(value) )
        return matched

    @property
    def json (self) :
        if self._json is None :
            self._json = myPyJSON(splat=self.wants_splat(), cascade=self.wants_cascade())
        return self._json

    @property
    def selected (self) :
        ok = lambda x: True
        if self.switches.get("where") :
            (key,value)=self.switches.get('where').split(":", 1)
            ok = lambda x: self.data_matches(x, key, value)
        return ok

    def is_multiline_output (self, output=None) :
        out = ( self.output ) if output is None else ( output )
        return ( len(out) > 1 )

    def get_output_terminator (self, output=None) :
        terminal="\n" if ( self.wants_table() or self.is_multiline_output(output) ) else ""
        return terminal
        
    def get_output_format (self, index=0) :
        sSpec = self.switches.get('output') if self.switches.get('output') is not None else self._default_mime
        aSpec = sSpec.split(";")
        return aSpec[index] if (index<len(aSpec)) else None

    def get_printf_template (self) :
        return self.switches.get('template')

    def add_output (self, value, key=None, pair=False, table={}, context={}) :
        out = self.get_output(value, key, pair, table, context)

        if isinstance(out, list) :
            self.output.extend( out )
        else :
            self.add_flag("output_error", out )

    def get_json_indent (self) :
        indent=None
        fmt=self.get_output_format(index=1)
        fmt=fmt if fmt is not None else ''
        if self.switches.get('indent') is not None :
            try :
                indent=int(self.switches.get('indent'))
            except ValueError as e:
                indent=str(self.switches.get('indent'))
        elif self.get_output_format(index=1)=='prettyprint' :
            indent=0
        elif re.match(r'^indent=(.*)$', fmt) :
            m=re.search(r'^indent=(.*)$', fmt)
            try :
                indent=int(m.group(1))
            except ValueError as e:
                indent=str(m.group(1))
        return indent

    def get_output (self, value, key=None, pair=False, table={}, context={}) :
        lines = []
        if ( self.get_output_format() == 'urlencode' or self.get_output_format() == "multipart/form-data" ) :
            sValue = str(value)
            display_value = urllib.parse.quote(sValue.encode("utf-8", "surrogatepass"))
        else :
            display_value = str(value)
            
        if (pair) :
            lines.extend([ "%(key)s\t%(value)s" % {"key": key, "value": display_value}])
        else :
            lines.extend([ display_value ])
                
        return lines

    def display_templated_text (self, text, table) :
        data = { **table, **{ "$n": "\n", "$t": "\t", "$json": json.dumps(table) } }

        # Here is an ugly but functional way to process backslash escapes in the template
        # via <https://stackoverflow.com/questions/4020539/process-escape-sequences-in-a-string-in-python/37059682#37059682>
        text_template = codecs.escape_decode(bytes(text, "utf-8"))[0].decode("utf-8")
        
        result = ( text_template % data )
        return result

    def display_data_dict (self, table, context, parse, keys=None, depth=0) :
        l_keys = ( table.keys() if keys is None or len(keys)==0 else [ key for key in keys ] )
        out = {} if self.wants_json_output() else []
        paired=( self.wants_table() or (len(l_keys) > 1) )
        try :
            for key in l_keys :
                if self.wants_json_output() :
                    out = { **out, **{ key: table[key] } } if not self.switched('without-key') else table[key]
                elif len(l_keys) < 2 and type(table[key]) is list :
                    self.display_data_list(table[key], context, parse, depth=depth+1)
                elif len(l_keys) < 2 and type(table[key]) is dict :
                    self.display_data_dict(table[key], context, parse, keys=None, depth=depth+1)
                else :
                    out.extend( self.get_output(table[key], key, pair=paired, table=table, context=context ) )
        except KeyError as e :
            self.add_flag("key_error", key)
        
        if self.wants_printf_output() :
            try :
                text = self.display_templated_text(self.get_printf_template(), table)
                self.output.append(text);
            except KeyError as e :
                self.add_flag("key_error", key)
        elif self.wants_json_output() :
            self.output.extend([ json.dumps(out,indent=self.get_json_indent()) ])
        elif self.wants_table() or isinstance(context, list) :
            line = "\t".join(out)
            self.output.extend([ line ])
        else :
            self.output.extend(out)
    
    def display_data_list (self, table, context, parse, depth=0) :
        i = 0
        for item in table :
            if self.selected(item) :
                if parse :
                    self.display_data(item, context, 0, depth=depth+1)
                elif type(item) is list :
                    line = "\t".join(item)
                    self.output.extend([ line ])
                else :
                    self.add_output(item, table=table, context=context)
                i = i + 1
    
    @property
    def data_keys (self) :
        return self.switches.get("key", [])
    
    @property
    def data_values (self) :
        return self.switches.get("value", [])
    
    def test_format (self, format1, format2) :
        result = None # nothing until proven something
        pattern = re.compile(r'^(([^/]+)/)?([^;]+)(;\s*(\S.*))?$')
        ( major1, minor1, parameter1 ) = ( None, None, None )
        ( major2, minor2, parameter2 ) = ( None, None, None )
        m = re.match(pattern, format1)
        if m :
            ( major1, minor1, parameter1 ) = ( m.group(2), m.group(3), m.group(5) )
        m = re.match(pattern, format2)
        if m :
            ( major2, minor2, parameter2 ) = ( m.group(2), m.group(3), m.group(5) )
        
        # Not so strict -- allow application/json == json, text/html = html, etc.
        if major2 is None :
            major2 = major1
        # Not so strict -- interpret 'text' (or 'text/text') as 'text/plain'
        if major2 == 'text' and minor2 == 'text' :
            minor2 = 'plain'
        if parameter2 is None :
            parameter2 = parameter1
        result = all([major1 == major2, minor1 == minor2, parameter1 == parameter2])
        return result
        
    def test_input_format(self, format) :
        return self.test_format(format, self.switches.get('input', 'text/plain'))
    
    def get_value (self, i, default=None) :
        value = self.data_values[i] if i<len(self.data_values) else default
        if self.test_input_format('application/json') :
            jsonParser = myPyJSON()
            jsonParser.accept(value)
            result = jsonParser.allData
        else :
            result = value
        return result
    
    def display_data (self, table, context, parse, depth=0) :
        if ( isinstance(table, dict) ) :
            self.display_data_dict(table, context, parse, keys=self.data_keys, depth=depth+1)
        elif ( isinstance(table, list) ) :
            self.display_data_list(table, context, parse, depth=depth+1)
        elif ( ( table is not None ) or ( depth > 1 ) ) :
            self.add_output(table, table=table, context=context)

    def display_regex (self) :
        # Replace non-capturing (?: ... ) with widely supported, grep -E compliant ( ... )
        print(re.sub(r'[(][?][:]', '(', self.json.prolog), end="")

    def format_line (self, line) :
        output = line if not self.switched('prolog') else self.json.add_prolog(line)
        output = output if not self.switched('epilog') else ( output + "\n" )
        return output
        
    def display_keyvalue (self) :
        self._default_mime = "application/json"
        table = {}
        for key_i in range(0, len(self.data_keys)) :
            ( key, value ) = ( self.data_keys[key_i], self.get_value(key_i) if key_i < len(self.data_values) else None )
            table[key] = value
        self.display_data(table, table, parse=True, depth=0)
        
        oData = ADPNDataConverter(table)
        oData.output = self.output
        oData.write_output(template=lambda s: self.format_line(s), end=self.get_output_terminator())
    
    def get_json_input (self) :
        table = None
        try :
            lineInput = [ line for line in fileinput.input() ]
            self.json.accept( lineInput )
            self.json.select_where(self.selected)
            table = self.json.allData
        except json.decoder.JSONDecodeError as e :
            # This might be the full text of a report. Can we find the JSON PACKET:
            # envelope nestled within it and strip out the other stuff?
            self.json.accept( lineInput, screen=True ) 
            self.json.select_where(self.selected)
            table = self.json.allData
        
        if self.switched('key+') :
            key=self.switches.get('key+')
            
            old_value=table.get(key)
            new_value=self.switches.get('value+')
            if new_value is None :
                old_value=None
                new_value=self.switches.get('value:')

            if old_value is None :
                value=new_value
            elif type(old_value) is list and not type(new_value) is list :
                value=[ item for item in old_value ]
                value.append(new_value)
            else :
                value=(old_value + new_value)
            table = { **table, **{ key: value } }
        
        if self.switched('into') :
            key = self.switches.get('into')
            table = { key: table }
        
        return table
        
    def execute (self, terminate=True) :

        super().execute(terminate=False)

        if script.switched('regex') :
            script.display_regex()
        elif script.switched('key') and script.switched('value', just_present=True) :
            script.display_keyvalue()
        else :
            try :
                table = self.get_json_input()
            
                self.display_data(table, table, self.switches.get('parse'))
                
                oData = ADPNDataConverter(table)
                oData.output = self.output
                oData.write_output(template=lambda s: self.format_line(s), end=self.get_output_terminator())
            
            except json.decoder.JSONDecodeError as e :

                self.add_flag("json_error", self.json.raw)
        
        for err in self.flags["json_error"] :
            if not self.switched('quiet') :
                self.write_error(2, "JSON encoding error. Could not extract data or key-value pairs from the provided data: '%(json)s'" % {"json": err.strip()})
        
        if terminate :
            self.exit()
    
if __name__ == '__main__' :

    scriptpath = sys.argv[0]
    
    (sys.argv, switches) = myPyCommandLine(sys.argv, defaults={
        "key": [], "value": [],
        "key:": None, "key+": None, "value:": None, "value+": None,
        "output": None, "input": "text/plain",
        "prolog": False, "epilog": False
    }).parse()
    
    script = ADPNGetJSON(scriptpath, sys.argv, switches)
    script.execute()
    script.exit()

