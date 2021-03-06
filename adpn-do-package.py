#!/usr/bin/python3
#
# adpn-do-package.py: package a directory of files intended for preservation
# into a LOCKSS Archival Unit (AU), following conventions from ADPNet
# <http://www.adpn.org/wiki/HOWTO:_Package_files_for_staging_on_the_Drop_Server>
#
# @version 2021.0823

import io, os, sys
import fileinput, stat
import re, json, numbers
import urllib
from paramiko import ssh_exception
from datetime import datetime
from getpass import getpass, getuser
from myLockssScripts import myPyCommandLine, myPyJSON, align_switches, shift_args
from ADPNCommandLineTool import ADPNCommandLineTool
from ADPNPreservationPackage import ADPNPreservationPackage, myLockssPlugin

python_std_input = input
def input (*args) :
    old_stdout = sys.stdout
    try :
        sys.stdout = sys.stderr
        return python_std_input(*args)
    finally :
        sys.stdout = old_stdout

class ADPNPackageContentScript(ADPNCommandLineTool) :
    """
Usage: adpn-do-package.py [<PATH>] [<OPTIONS>]...

  --local=<PATH>   	   	the local directory containing the files to stage
  --au_title=<TITLE>   	the human-readable title for the contents of this AU
  --subdirectory=<SLUG>	the subdirectory on the staging server to hold AU files
  --directory=<SLUG>   	identical to --subdirectory
  --backup=<PATH>      	path to store current contents (if any) of staging location
  
Output and Diagnostics:

  --output=<MIME>      	text/plain or application/json
  --verbose=<LEVEL>   	level (0-2) of diagnostic output for packaging/validation
  --quiet             	identical to --verbose=0
  
Common configuration parameters:

  --base_url=<URL>     	WWW: the URL for web access to the staging area
  --institution=<NAME>  Manifest: human-readable nmae of the institution

Default values for these parameters can be set in the JSON configuration file
adpnet.json, located in the same directory as the script. To set a default
value, add a key-value pair to the hash table with a key based on the name of
the switch. For example, to set the default value for the --institution switch
to "Alabama Department of Archives and History", add the following pair to the
hash table:

    {
        ...
        "institution": "Alabama Department of Archives and History",
        ...
    }
    
The default values in adpnet.json are overridden if values are provided on the
command line with explicit switches.
    """
    
    def __init__ (self, scriptpath, argv, switches, scriptname=None) :
        super().__init__(scriptpath=scriptpath, argv=argv, switches=switches, scriptname=scriptname)

        # start out with defaults
        self.manifest_data = None
        self._package = None
        self._plugin = None
        self._plugin_parameters = None
    
    @property
    def subdirectory (self) :
        return self.switches.get('directory') if switches.get('directory') is not None else self.switches.get('subdirectory')
        
    @subdirectory.setter
    def subdirectory (self, rhs) :
        self.switches['subdirectory'] = rhs
        self.switches['directory'] = rhs
    
    @property
    def institution_code (self) :
        code = None
        if self.switched('stage/user') :
            code = self.switches.get('stage/user')
        elif self.switched('stage/base') :
            url = self.switches.get('stage/base')
            (host, user, passwd, base_dir, subdirectory) = (None, None, None, None, None)
        
            bits=urllib.parse.urlparse(url)
            if len(bits.netloc) > 0 :
                netloc = bits.netloc.split('@', 1)
                netloc.reverse()
                (host, credentials)=(netloc[0], netloc[1] if len(netloc) > 1 else None)
                credentials=credentials.split(':', 1) if credentials is not None else [None, None]
                (user, passwd) = (credentials[0], credentials[1] if len(credentials) > 1 else None)
            
            code = user
        return code
    
    def get_location (self) :
        return os.path.realpath(os.path.expanduser(self.switches.get('local'))) if self.switches.get('local') else os.path.realpath(".")
    
    @property
    def package (self) :
        return self._package
    
    @package.setter
    def package (self, rhs) :
        self._package = rhs
    
    def get_itemparent (self, file) :
        canonical = os.path.realpath(file)
        return os.path.dirname(canonical)

    def exclude_filesystem_artifacts (self, file) :
        return file.lower() in ['thumbs.db']
    
    @property
    def plugin_parameters (self) :
        if self._plugin_parameters is None :
            self._plugin_parameters = self.get_plugin_parameters()
        return self._plugin_parameters
    
    @property
    def plugin (self) :
        if self._plugin is None :
            self._plugin = self.get_plugin()
        return self._plugin
        
    def get_plugin (self) :
        return self.package.plugin if self.package is not None else myLockssPlugin(jar=self.switches.get("jar"))
    
    def get_plugin_parameters (self) :
        # Let's determine the plugin and its parameters from the command line switches
        return [ [parameter, setting] for (parameter, setting) in self.switches.items() if parameter in self.plugin.get_parameter_keys(names=True) ]

    def new_preservation_package (self) :
        # Now let's plug the parameters for this package in to the package and plugin
        pack = ADPNPreservationPackage(path=self.get_location(), plugin=self.plugin, plugin_parameters=self.plugin_parameters, switches=self.switches)

        # FIXME: we need to figure out a good way to extract & apply this setting...
        pack.staging_user = self.institution_code
        return pack
        
    def get_manifest_data (self, key=None) :
        data = None
        if self.manifest_data is None :
            self.manifest_data = self.package.read_manifest_data()
        if type(self.manifest_data) is dict :
            data = self.manifest_data.get(key) if key is not None else self.manifest_data
        return data
    
    @property
    def au_title (self) :
        return self.get_au_title(load_manifest=False)
    
    @au_title.setter
    def au_title (self, rhs) :
        self.switches['au_title'] = rhs
        if self.package is not None :
            self.package.au_title = rhs
            
    def get_au_title (self, load_manifest=True, use_directory=False) :
        au_title = self.switches.get('au_title')
        if load_manifest and not au_title :
            au_title = self.get_manifest_data("AU Package")
        if load_manifest and not au_title :
            au_title = self.get_manifest_data("Ingest Title")
        if use_directory and not au_title :
            au_title = self.subdirectory 
        return au_title
        
    def get_au_start_url (self) :
        au_start_url = None
        
        details_list = self.package.plugin.get_details(check_parameters=True) # bolt on missing parameter(s)
        details = {}
        for detail in details_list :
            details[detail['name']] = detail['value']
        au_start_url = details['Start URL']
        return au_start_url
        
    def execute (self, terminate=True) :
        super().execute(terminate=False)
        
        try :
            if self.subdirectory is None :
                self.subdirectory = os.path.basename(self.get_location())
                self.write_status("Using present working directory name for staging area subdirectory: %(subdirectory)s" % { "subdirectory": self.subdirectory }, verbosity=1)
            self.package = self.new_preservation_package()

            if self.get_au_title() is None :
                self.au_title = input("AU Title [%(default)s]: " % { "default": self.subdirectory })

            # STEP 1. Confirm that we have all the plugin parameters required to produce AU Start URL
            self.write_status("* Confirming required LOCKSS plugin parameters", verbosity=2)
            au_start_url = self.get_au_start_url()

            # STEP 2. Check BagIt enclosure of files packaged in the AU
            if not ( self.package.has_bagit_enclosure() and self.test_skip("scan") ) :
                self.write_status("* Checking BagIt packaging: %(path)s" % {"path": self.package.get_path(canonicalize=True)}, verbosity=1)
                self.package.make_bagit_enclosure(halt=True, validate=True)
            else :
                self.write_status("* Skipped BagIt validation: %(path)s" % {"path": self.package.get_path(canonicalize=True)}, verbosity=1)

            # STEP 3. Request manifest HTML from MakeManifest service and write file
            if self.package.has_manifest() and not self.switches.get('manifest') :
                self.write_status("* Confirming manifest HTML: %(path)s" % { "path": self.package.plugin.get_manifest_filename() }, verbosity=1 )
                self.package.check_manifest()
            else :
                self.write_status("* Requesting LOCKSS manifest HTML from service: %(path)s" % { "path": self.package.plugin.get_manifest_filename() }, verbosity=1 )
                self.package.make_manifest()
            
            # STEP 4. Feed parameter settings in to LOCKSS plugin, get out AU details,
            # and package it all together into JSON data output.
            out_packet = self.package.get_pipeline_metadata(cascade={ "Ingest Step": "packaged" }, read_manifest=True)
            
            # STEP 5. Send JSON data output to stdout/pipeline
            self.write_output(data=out_packet, prolog="JSON PACKET:\t")

        except AssertionError as e : # Parameter requirements failure
            if "BagIt" == e.args[0] :
                self.write_error((100 + e.args[3]), "%(message)s on %(path)s, exit code %(code)d. Output:" % {
                    "message": e.args[1],
                    "path": os.path.realpath(e.args[2]),
                    "code": e.args[3]
                })
                print ( "\n".join(e.args[4]), file=sys.stderr)
            elif "manifest" == e.args[0] :
                self.write_error(4, "%(message)s for %(path)s. Required boilerplate: %(phrase)s" % {
                    "message": e.args[1],
                    "path": os.path.realpath(e.args[2]),
                    "phrase": e.args[3]
                })
            elif len(e.args) == 2 :
                ( message, req ) = e.args
                print("ERR:",file=sys.stderr)
                print(e.args,file=sys.stderr)
                missing = [ parameter for parameter in req if self.switches.get(parameter) is None ]
                self.write_error(2, "Required parameter missing: %(missing)s" % { "missing": ", ".join(missing) })
            else :
                ( message, req ) = ( e.args[0], None )
                self.write_error(2, "Requirement failure: %(message)s" % { "message": message })

        except KeyboardInterrupt as e :
            self.write_error(255, "Keyboard Interrupt.", prefix="^C\n")

        except FileNotFoundError as e :
            if 3 == self.exitcode :
                pass
            else :
                raise
        
        if terminate :
            self.exit()
        
    def exit (self) :
        sys.exit(self.exitcode)

if __name__ == '__main__':

    scriptpath = os.path.realpath(sys.argv[0])
    scriptname = os.path.basename(scriptpath)
    scriptdir = os.path.dirname(sys.argv[0])
    configjson = "/".join([scriptdir, "adpnet.json"])
    
    os.environ["PATH"] = ":".join( [ scriptdir, os.environ["PATH"] ] )
    
    (sys.argv, switches) = myPyCommandLine(sys.argv, defaults={
            "stage/base": None, "stage/host": None, "stage/user": None, "stage/pass": None, "stage/protocol": None,
            "user/realname": None, "user/email": None,
            "jar": None,
            "subdirectory": None, "directory": None,
            "base_dir": None, "output": "text/plain",
            "remote": None, "local": None, "backup": os.path.expanduser("~/backup"),
            "verbose": 1, "quiet": False,
            "base_url": None, "stage/base_url": None,
            "au_title": None, "au_notes": None, "au_file_size": None, "institution": None,
            "skip": None,
            "proxy": None, "port": None, "tunnel": None, "tunnel-port": None,
            "manifest": None, "context": scriptname
    }, configfile=configjson, settingsgroup=["stage", "ftp", "user"]).parse()
    
    align_switches("directory", "subdirectory", switches)
    align_switches("base_url", "stage/base_url", switches)
    
    args = sys.argv[1:]
    
    # look for positional arguments: first argument goes to --local=...
    if switches.get('local') is None :
        if len(args) > 0 :
            ( switches['local'], args ) = shift_args(args)
    # look for positional arguments: next argument goes to --remote=...
    if switches.get('remote') is None :
        if len(args) > 0 :
            ( switches['remote'], args ) = shift_args(args)
    align_switches("remote", "stage/base", switches)
    
    script = ADPNPackageContentScript(scriptpath, sys.argv, switches, scriptname=switches.get('context'))
    
    if script.switched('details') :
        print("Defaults:", defaults)
        print("")
        print("Settings:", switches)
    else :
        script.execute()
    script.exit()
    