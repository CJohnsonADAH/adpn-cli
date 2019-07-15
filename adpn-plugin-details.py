#!/usr/bin/python3
#
# adpn-ingest-test: Assemble information and run tests for a package of files staged for
# ingest as a LOCKSS Archival Unit, given a local location, a LOCKSS Plugin and parameters
# for the plugin.
#
# Switches can be provided on the command line, or interactively on the console at input
# prompts. You can set default values for commonly-repeated switches (for example, if your
# LOCKSS daemon is always at the same location, you won't need to re-enter that location
# every time you run the script) by creating a plaintext file called:
#
# 		./adpn-ingest-test.defaults.conf
#
# where the conf file is located in the same directory as the adpn-ingest-test script.
# The file should be a text/plain file, with one switch on each line of the file. If the
# same switch is provided on the command line, the value on the command line overrides the
# value provided in the defaults.conf file.
#
# @version 2019.0625

import os
import sys
import json
import subprocess
import myLockssScripts
from getpass import getpass
from myLockssScripts import myPyCommandLine, myPyPipeline

##########################################################################################
### CONFIGURATION: Set up some constants #################################################
##########################################################################################

#SCRIPTDIR=`dirname $0`
#SCRIPT=`basename $0`
#PATH=${SCRIPTDIR}:${PATH}
#CONFFILE="${SCRIPTDIR}/${SCRIPT}.defaults.conf"
#
#PLUGINTXT=`mktemp`

##########################################################################################
### DEPENDENCIES: check for required command-line tools and Python scripts ###############
##########################################################################################
#
#declare -A DEPENDENCIES ; DEPENDENCIES=(
#	[mktemp]="command-line %s tool"
#	[grep]="command-line %s tool"
#	[xargs]="command-line %s tool"
#	[du]="command-line %s tool"
#	[find]="command-line %s tool"
#	[adpn-plugin-info]="%s Bash script"
#	[lockss-plugin-url.py]="%s Python script"
#	[lockss-retrieve-jar.py]="%s Python script"
#	[lockss-plugin-props.py]="%s Python script"
#	[lockss-plugin-props-print-parameter.py]="%s Python script"
#	[adpn-ingest-test-url-ok.py]="%s Python script"
#)
#
#DEPENDENCY_FAILURE=""
#for CMD in "${!DEPENDENCIES[@]}" ; do
#	DESC=$(printf "${DEPENDENCIES[$CMD]}" "${CMD}")
#	if [[ -z $(which ${CMD}) ]] ; then
#		echo 1>&2
#		echo Dependency Failure: ${CMD}. This script requires the ${DESC}. 1>&2
#		DEPENDENCY_FAILURE="${DEPENDENCY_FAILURE}+${CMD}"
#	fi
#done
#
#if [[ ! -z "${DEPENDENCY_FAILURE}" ]] ; then
#	exit 255
#fi

class ADPNPluginDetailsScript :
	"""
Usage:

  adpn-plugin-details.py [OPTION]...

    --local=<PATH>           	path to the files being put into the AU (e.g.: 'w:\\Path')
    --au_title=<TITLE>       	title for this AU in titledb (e.g.: 'ADAH Lovely Files')
    --<PARAM>=<VALUE>        	set plugin parameter <PARAM> to <VALUE>
                             	  (e.g.: subdirectory=Lovely-Files)

  To select and configure a plugin for this ingest, use:
    --jar=<URL>               	URL directly to a plugin's JAR file on the props server
    --plugin=<NAME>           	use the plugin named <NAME>
    --plugin-id=<FQCN>        	use the plugin with uniqid <FQCN>
    --plugin-regex=<PATTERN>  	use the plugin whose name matches <PATTERN>
    --plugin-keywords=<WORDS> 	use the plugin whose name contains keywords <WORDS>

  To connect to your LOCKSS daemon (to retrieve plugin lists):  
    --daemon=<HOST>:<PORT>   	Your LOCKSS daemon host (e.g.: adpnadah.alabama.gov:8081)
    --user=<USERNAME>        	The HTTP Auth username for your LOCKSS Daemon
    --pass=<PASSWORD>        	The HTTP Auth password for your LOCKSS Daemon
	
  Plugins will be hosted by the LOCKSS props server/admin node. If you need to connect
  to the LOCKSS props server through a SOCKS5 proxy, use:
    --proxy=<HOST>           	the name of your proxy (use localhost for an SSH tunnel)
    --port=<NUMBER>          	the port number for your proxy
	
  If you need to use SSH tunneling to connect to the SOCKS5 proxy, use:
    --tunnel=<HOST>          	the name of the host to open an SSH tunnel to
    --tunnel-port=<NUMBER>   	the port for SSH connections to the tunnel (default: 22)

  Network Admin:
    
  <input> | adpn-ingest-test - --remote [OPTION]...
  adpn-ingest-test <JSONFILE> --remote [OPTION]...
  
  JSON input provided from the local side can provide the au_title, plugin selection and
  values for required plugin parameters. Parameters for connecting to the LOCKSS daemon
  and to the props server are same as above. If you need to override a value provided by
  the JSON input, you can do so with a command-line switch (e.g., a stupid title provided
  in JSON can be overridden with --au_title='ADAH Better Title').
	"""

	def __init__ (self, scriptname, scriptdir, argv, switches) :
		self.exitcode = 0
		self.scriptname = scriptname
		self.scriptdir = scriptdir
		self.argv = argv
		self.switches = switches
		self.col0 = "all"
		os.environ["PATH"] = ":".join( [ self.scriptdir, os.environ["PATH"] ] )

	def has_at_least_one (self, candidates) :
		has = lambda key: self.switches.get(key) is not None
		got = [ has(key) for key in candidates ]
		return (sum(got) > 0)

	def has_all (self, candidates) :
		has = lambda key: self.switches.get(key) is not None
		got = [ has(key) for key in candidates ]
		return (sum(got) == len(got))

	def needs_daemon_switches (self) :
		return self.has_at_least_one(['plugin', 'plugin-regex', 'plugin-keywords', 'plugin-id'])
	
	def daemon_switches (self, pairs=False) :
		return self.get_switch_params(['daemon', 'user', 'pass'], pairs)
	
	def printable_daemon_switches (self, pairs=False) :
		return self.get_switch_params(['daemon', 'user'], pairs)
	
	def plugin_url_switches (self, pairs=False) :
		return self.get_switch_params(self.plugin_switches() + self.daemon_switches(), pairs)
		
	def plugin_switches (self, pairs=False) :
		return self.get_switch_params(['jar', 'plugin', 'plugin-regex', 'plugin-keywords', 'plugin-id'], pairs)
		
	def proxy_switches (self, pairs=False) :
		return self.get_switch_params(['proxy', 'port', 'tunnel', 'tunnel-port'], pairs)
	
	def get_switch_params (self, keys, pairs=True) :
		return keys if not pairs else [(k, self.switches[k]) for k in self.switches if k in keys]
		
	def has_daemon_switches (self) :
		return self.has_all(self.daemon_switches())
	
	def has_proxy_switches (self) :
		return self.has_at_least_one(self.proxy_switches())
	
	def has_plugin_criteria (self) :
		return self.has_at_least_one(self.plugin_switches())

	def do_read_daemon_switches (self) :
		if self.switches.get('user') is None or len(self.switches.get('user')) == 0 :
			self.switches['user'] = input("LOCKSS Daemon Username: ")
		if self.switches.get('pass') is None or len(self.switches.get('pass')) == 0 :
			self.switches['pass'] = getpass("LOCKSS Daemon Password: ")
	
	def get_jars (self) :
		code = 0
		try :
			the_jars = [ self.switches['jar'] + '' ]
		except (KeyError, TypeError) :

			cmdline = myPyCommandLine(['lockss-plugin-url.py']).compose(self.plugin_url_switches(pairs=True))
			
			try:
				buf = subprocess.check_output(cmdline)
			except subprocess.CalledProcessError as e :
				code = e.returncode
				buf = e.output
			finally :
				output = buf.decode()
				the_jars = [ jar for jar in filter(lambda line: len(line.rstrip()) > 0, output.split("\n")) ]
				
		finally :
		
			self.exitcode = code
			
		return the_jars

	def cmdLineScript (self, script_args, params, pass_along) :
		return myPyCommandLine(script_args).compose(params + [
			(key, self.switches[key]) for key in self.switches if key in pass_along
		] )

	def pADPNPluginInfo (self, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, encoding="utf-8") :
		json_params = json.loads(self.switches["parameters"])
		params = [ (key, json_params[key]) for key in json_params ] if json_params is not None else [ ]
		
		cmdAPI = self.cmdLineScript([
			'adpn-plugin-info', '-', '--quiet'
		], [ ('format', 'text/tab-separated-values'), ('jar', self.jar_url) ] + params, self.proxy_switches())
		return subprocess.Popen(cmdAPI, stdin=stdin, stdout=stdout, stderr=stderr, encoding=encoding)
		
	def pLockssRetrieveJar (self, stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr, encoding="utf-8") :
		cmdLRJ = self.cmdLineScript([ 'lockss-retrieve-jar.py' ], [ ('url', self.jar_url) ], self.proxy_switches())
		return subprocess.Popen(cmdLRJ, stdin=stdin, stdout=stdout, stderr=stderr, encoding=encoding)

	def display_usage (self) :
		print(self.__doc__)

	def display_section_header(self, header: str, code: str) :
		if self.switches['output']=='text/tab-separated-values' :
			self.col0 = code
		else : # text/plain
			print("")
			print(header.upper())
			print("=" * len(header))
	
	def display_key_value(self, key, value, rest=None) :
		if self.switches['output']=='text/tab-separated-values' :
			line = "%(code)s\t%(key)s\t%(value)s\t%(rest)s" if rest is not None else "%(code)s\t%(key)s\t%(value)s"
			print(line % {"code": self.col0, "key": key, "value": value, "rest": rest})
		else : # text/plain
			head = key.upper() + ":" if self.col0 in ['parameter', 'detail', 'setting'] else key
			pad = (" " * (self.padlen - len(head)))
			line = "%(key)s\t%(value)s\t%(rest)s" if rest is not None else "%(key)s\t%(value)s"
			
			print(line % {"key": head + pad, "value": value, "rest": rest})
	
	def display_details (self, buf) :
		plugin_details = {}
		for line in buf.split("\n") :
			if len(line.rstrip()) > 0 :
				fields = line.rstrip().split("\t", 2)
				key = fields[0]
				value = fields[1] if len(fields) > 1 else None
				rest = fields[2] if len(fields) > 2 else None
				plugin_details[key] = (value, rest)

		self.display_section_header("Plugin Details:", "detail")
			
		group1 = ['Plugin JAR', 'Plugin Name', 'Plugin Version', 'Plugin ID']
		group2 = ['Start URL', 'Manifest URL']
		group3 = [ key for key in plugin_details if key.find("PARAM(")==0 ]
		group4 = [ key for key in plugin_details if not key in (group1+group2+group3) ]
			
		padlen1 = max([ len(label)+1 for label in group1 + group2 + group4 ])
		padlen3 = max([ len(plugin_details[key][0]) for key in group3 ])
		self.padlen = max(padlen1, padlen3)
			
		for key in group1 + group2 :
			try :
				(value, rest) = plugin_details[key]
				self.display_key_value(key, value, rest)
					
			except KeyError as e :
				pass
			
		self.display_section_header("Required Parameters:", "parameter")
			
		for key in group3 :
			type = key[6:-2]
			try :
				(value, rest) = plugin_details[key]
				valuetype = (rest + ' ' if rest is not None else ' ')
				valuetype = valuetype + "(" + type + ")" 
				self.display_key_value(value, valuetype)
					
			except KeyError as e :
				pass		

		self.display_section_header("Derived Settings:", "setting")

		for key in group4 :
			try :
				(value, rest) = plugin_details[key]
				self.display_key_value(key, value, rest)
					
			except KeyError as e :
				pass
	
	def display_error (self, message) :
		print("[%(scriptname)s] %(message)s" % {"scriptname": self.scriptname, "message": message}, file=sys.stderr)
		
	def execute (self) :
		jars = self.get_jars()
		if len(jars) == 0 :
			self.exitcode = 2
			sw = myPyCommandLine([]).compose(self.plugin_switches(pairs=True) + self.printable_daemon_switches(pairs=True))
			self.display_error("No Publisher Plugin matches %(criteria)s" % {"criteria": sw})
		elif len(jars) > 1 :
			self.exitcode = 1
			self.display_section_header("Multiple Matching Plugins:", "multiple")
			jarTitles = [ jar.split("\t")[0] for jar in jars ]
			self.padlen = max([ len(jarTitle) for jarTitle in jarTitles ])
			
			for jar in jars :
				(jarTitle, jarUrl) = jar.split("\t")
				self.display_key_value(jarTitle, jarUrl)
				
		else :
			self.jar_url = jars[0]

			(buf, errbuf, code) = myPyPipeline([self.pLockssRetrieveJar, self.pADPNPluginInfo]).siphon()
			
			if code[1] == 0 :
				self.display_details(buf)
			self.exitcode = 2 if code[1]==1 else code[1]
			
	def exit (self) :
		sys.exit(self.exitcode)

if __name__ == '__main__':

	scriptname = os.path.basename(sys.argv[0])
	scriptdir = os.path.dirname(sys.argv[0])
	
	(sys.argv, switches) = myPyCommandLine(sys.argv, defaults={
	"jar": None,
	"plugin": None, "plugin-regex": None, "plugin-keywords": None, "plugin-id": None,
	"daemon": None, "user": None, "pass": None, 
	"proxy": None, "port": None, "tunnel": None, "tunnel-port": None,
	"output": "text/plain", "parameters": "null"
	}).parse()

#if [[ "$1" == "-" || "$1" =~ [.]json$ ]] ; then
#	./adpn-json-to-switches.py $1 >> "${CMDLINETXT}"
#	shift
#	
#	cat "${CMDLINETXT}" | while IFS="" read -r SWITCH ; do
#		_ARGV+=("${SWITCH}")
#	done
#fi

#SWITCHFILES+=(${CMDLINETXT})

#			*)
#				SUBARGV_ADPNPLUGININFO[$KEY]="--${KEY}=${VALUE}"
#				;;
#		esac
#		

script = ADPNPluginDetailsScript(scriptname, scriptdir, sys.argv, switches)
if switches.get('help') :
	script.display_usage()
elif (script.has_plugin_criteria()) :
	script.execute()
else :
	script.display_usage()

script.exit()

##########################################################################################
### ERRORS: List any errors reported by subsidiary scripts ###############################
##########################################################################################

#if [ ! -z "${ERROR_ON}" ] ; then
#	EXITCODE=1
#	
#	echo ""
#	echo "INGEST TEST ERRORS:"
#	echo "-------------------"
#	for mod in ${ERROR_ON} ; do
#		echo "Failed: ${mod}"
#	done
#fi