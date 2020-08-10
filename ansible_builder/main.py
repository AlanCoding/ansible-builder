import filecmp
import os
import shutil
import textwrap
import yaml

from . import constants
from .colors import MessageColors
from .steps import AdditionalBuildSteps, GalaxySteps, PipSteps, IntrospectionSteps, BindepSteps
from .utils import run_command
from .requirements import sanitize_requirements, sanitize_bindep
import ansible_builder.introspect


# Files that need to be moved into the build context
CONTEXT_FILES = ['galaxy', 'python', 'system']


class DefinitionError(RuntimeError):
    pass


class AnsibleBuilder:
    def __init__(self, action=None,
                 filename=constants.default_file,
                 base_image=constants.default_base_image,
                 build_context=constants.default_build_context,
                 tag=constants.default_tag,
                 container_runtime=constants.default_container_runtime):
        self.action = action
        self.definition = UserDefinition(filename=filename)
        self.tag = tag
        self.build_context = build_context
        self.container_runtime = container_runtime
        self.containerfile = Containerfile(
            definition=self.definition,
            base_image=base_image,
            build_context=self.build_context,
            container_runtime=self.container_runtime,
            tag=self.tag)

    @property
    def version(self):
        return self.definition.version

    @property
    def build_command(self):
        return [
            self.container_runtime, "build",
            "-f", self.containerfile.path,
            "-t", self.tag,
            self.build_context
        ]

    @property
    def introspect_command(self):
        return [
            self.container_runtime, "run",
            "--rm", self.tag,
            "introspect"
        ]

    def build(self):
        self.containerfile.create_folder_copy_files()
        self.containerfile.prepare_prepended_steps()
        self.containerfile.prepare_introspection_steps()
        self.containerfile.prepare_galaxy_steps()
        print(MessageColors.OK + 'Writing partial Containerfile without collection requirements' + MessageColors.ENDC)
        self.containerfile.write()
        run_command(self.build_command)
        rc, output = run_command(self.introspect_command, capture_output=True)
        collection_data = yaml.load("\n".join(output))
        self.containerfile.prepare_system_steps(collection_data['system'])
        self.containerfile.prepare_pip_steps(collection_data['python'])
        self.containerfile.prepare_appended_steps()
        print(MessageColors.OK + 'Rewriting Containerfile to capture collection requirements' + MessageColors.ENDC)
        self.containerfile.write()
        run_command(self.build_command)
        return True


class BaseDefinition:
    """Subclasses should populate these properties in the __init__ method
    self.raw - a dict that basically is the definition
    self.reference_path - the folder which dependencies are specified relative to
    """

    @property
    def version(self):
        version = self.raw.get('version')

        if not version:
            raise ValueError("Expected top-level 'version' key to be present.")

        return str(version)


class UserDefinition(BaseDefinition):
    def __init__(self, filename):
        self.filename = filename
        self.reference_path = os.path.dirname(filename)

        try:
            with open(filename, 'r') as f:
                y = yaml.safe_load(f)
                self.raw = y if y else {}
        except FileNotFoundError:
            raise DefinitionError("""
            Could not detect '{0}' file in this directory.
            Use -f to specify a different location.
            """.format(constants.default_file))
        except yaml.parser.ParserError as e:
            raise DefinitionError(textwrap.dedent(MessageColors.FAIL + """
            An error occured while parsing the definition file:
            {0}
            """).format(str(e)) + MessageColors.ENDC)

        if not isinstance(self.raw, dict):
            raise DefinitionError(
                MessageColors.FAIL + 'Definition must be a dictionary, not {}'.format(type(self.raw).__name__) + MessageColors.ENDC
            )

    def get_additional_commands(self):
        """Gets additional commands from the exec env file, if any are specified.
        """
        commands = self.raw.get('additional_build_steps')
        return commands

    def get_dep_abs_path(self, entry):
        """Unique to the user EE definition, files can be referenced by either
        an absolute path or a path relative to the EE definition folder
        This method will return the absolute path.
        """
        req_file = self.raw.get('dependencies', {}).get(entry)

        if not req_file:
            return None

        if os.path.isabs(req_file):
            return req_file

        return os.path.join(self.reference_path, req_file)

    def get_dep(self, entry):
        """Returns the filename of the file within the build context.
        """
        original_path = self.get_dep_abs_path(entry)
        if original_path:
            return os.path.basename(original_path)
        return original_path

    def validate(self):
        bc_files = set(['introspect.py', 'Dockerfile', 'Containerfile'])
        for item in CONTEXT_FILES:
            requirement_path = self.get_dep_abs_path(item)
            if requirement_path:
                filename = os.path.basename(requirement_path)
                if filename in bc_files:
                    raise DefinitionError(
                        MessageColors.WARNING + 'Duplicated filename {} in definition.'.format(filename) + MessageColors.ENDC
                    )
                if not os.path.exists(requirement_path):
                    raise DefinitionError(
                        MessageColors.WARNING + 'Dependency file {} does not exist.'.format(requirement_path) + MessageColors.ENDC
                    )
                bc_files.add(filename)
        additional_cmds = self.get_additional_commands()
        if additional_cmds:
            if not isinstance(additional_cmds, dict):
                raise DefinitionError(
                    "Expected 'additional_build_steps' in the provided definition file to be a dictionary "
                    f"with keys 'prepend' and/or 'append', found a {type(additional_cmds)} instead.")
            expected_keys = frozenset(('append', 'prepend'))
            unexpected_keys = set(additional_cmds.keys()) - expected_keys
            if unexpected_keys:
                raise DefinitionError(
                    f"Keys {*unexpected_keys,} are not allowed in 'additional_build_steps'."
                )


class Containerfile:
    newline_char = '\n'

    def __init__(self, definition,
                 build_context=constants.default_build_context,
                 base_image=constants.default_base_image,
                 container_runtime=constants.default_container_runtime,
                 tag=constants.default_tag):

        self.build_context = build_context
        self.definition = definition
        filename = constants.runtime_files[container_runtime]
        self.path = os.path.join(self.build_context, filename)
        self.base_image = base_image
        self.container_runtime = container_runtime
        self.tag = tag
        self.steps = [
            "FROM {}".format(self.base_image),
            ""
        ]

    def create_folder_copy_files(self):
        """Creates the build context file for this Containerfile
        moves files from the definition into the folder
        """
        # courteously validate items before starting to write files
        self.definition.validate()

        os.makedirs(self.build_context, exist_ok=True)

        for item in CONTEXT_FILES:
            requirement_path = self.definition.get_dep_abs_path(item)
            if requirement_path is None:
                continue
            if item == 'python':
                continue  # will be put into combined requirements.txt
            dest = os.path.join(self.build_context, os.path.basename(requirement_path))
            exists = os.path.exists(dest)
            do_copy = True
            if exists:
                do_copy = not filecmp.cmp(requirement_path, dest, shallow=False)
                if do_copy:
                    print(MessageColors.WARNING + 'File {} had modifications and will be rewritten'.format(dest) + MessageColors.ENDC)
            if do_copy:
                shutil.copy(requirement_path, self.build_context)

    def prepare_prepended_steps(self):
        additional_prepend_steps = self.definition.get_additional_commands()
        if additional_prepend_steps:
            prepended_steps = additional_prepend_steps.get('prepend')
            if prepended_steps:
                return self.steps.extend(AdditionalBuildSteps(prepended_steps))

        return False

    def prepare_appended_steps(self):
        additional_append_steps = self.definition.get_additional_commands()
        if additional_append_steps:
            appended_steps = additional_append_steps.get('append')
            if appended_steps:
                return self.steps.extend(AdditionalBuildSteps(appended_steps))

        return False

    def prepare_introspection_steps(self):
        source = ansible_builder.introspect.__file__
        dest = os.path.join(self.build_context, 'introspect.py')
        exists = os.path.exists(dest)
        if not exists or not filecmp.cmp(source, dest, shallow=False):
            shutil.copy(source, dest)

        self.steps.extend(IntrospectionSteps(os.path.basename(dest)))

    def prepare_galaxy_steps(self):
        galaxy_file = self.definition.get_dep('galaxy')
        if galaxy_file:
            self.steps.extend(GalaxySteps(galaxy_file))
        return self.steps

    def prepare_pip_steps(self, collection_pip):
        python_req_file = self.definition.get_dep('python')

        if python_req_file:
            with open(self.definition.get_dep_abs_path('python'), 'r') as f:
                user_py_reqs = f.read().split('\n')
            collection_pip['user'] = user_py_reqs
        pip_list = sanitize_requirements(collection_pip)

        py_req_text = '\n'.join(pip_list)
        if py_req_text.strip():
            pip_file = os.path.join(self.build_context, 'requirements.txt')
            with open(pip_file, 'w') as f:
                f.write(py_req_text)

            self.steps.extend(PipSteps('requirements.txt'))

        return self.steps

    def prepare_system_steps(self, collection_bindep):
        system_req_file = self.definition.get_dep('system')

        if system_req_file:
            with open(self.definition.get_dep_abs_path('system'), 'r') as f:
                user_py_reqs = f.read().split('\n')
            collection_bindep['user'] = user_py_reqs
        system_list = sanitize_bindep(collection_bindep)

        system_req_text = '\n'.join(system_list + [''])
        if system_req_text.strip():
            system_file = os.path.join(self.build_context, 'bindep.txt')
            with open(system_file, 'w') as f:
                f.write(system_req_text)

            self.steps.extend(BindepSteps('bindep.txt'))

        return self.steps

    def write(self):
        with open(self.path, 'w') as f:
            for step in self.steps:
                f.write(step + self.newline_char)

        return True
