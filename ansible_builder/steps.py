import os
import sys

from . import constants
from .colors import MessageColors


class Steps:
    def __iter__(self):
        return iter(self.steps)


class AdditionalBuildSteps(Steps):
    def __init__(self, additional_steps):
        """Allows for additional prepended / appended build steps to be
        in the Containerfile or Dockerfile.
        """
        self.steps = []
        if isinstance(additional_steps, str):
            lines = additional_steps.strip().splitlines()
        elif isinstance(additional_steps, list):
            lines = additional_steps
        else:
            print(MessageColors.FAIL + "Error: Unknown type found for additional_build_steps; "
                  "must be list or multi-line string." + MessageColors.ENDC)
            sys.exit(1)
        self.steps.extend(lines)

    def __iter__(self):
        return iter(self.steps)


class IntrospectionSteps(Steps):
    def __init__(self, context_file):
        self.steps = []
        self.steps.extend([
            "ADD {} /usr/local/bin/introspect".format(context_file),
            "RUN chmod +x /usr/local/bin/introspect"
        ])


class GalaxySteps(Steps):
    def __init__(self, requirements_naming):
        """Assumes given requirements file name has been placed in the build context
        """
        self.steps = []
        self.steps.append(
            "ADD {} /build/".format(requirements_naming)
        )
        self.steps.extend([
            "",
            "RUN ansible-galaxy role install -r /build/{0} --roles-path {1}".format(
                requirements_naming, constants.base_roles_path),
            "RUN ansible-galaxy collection install -r /build/{0} --collections-path {1}".format(
                requirements_naming, constants.base_collections_path)
        ])


class BindepSteps(Steps):
    def __init__(self, context_file, collection_files):
        self.steps = []
        if not context_file:
            return

        # requirements file added to build context
        self.steps.append("ADD {} /build/".format(context_file))
        self.steps.append("RUN pip3 install bindep")
        container_path = os.path.join('/build/', context_file)
        self.steps.append(
            'RUN bindep -b -f {} >> /build/bindep_out.txt'.format(container_path)
        )
        self.steps.append(
            "RUN if [ -s /build/bindep_out.txt ]; then dnf -y install $(cat /build/bindep_out.txt); fi"
        )


class PipSteps(Steps):
    def __init__(self, context_file):
        """Allows for 1 python requirement file in the build context"""
        self.steps = []
        if not context_file:
            return

        # requirements file added to build context
        self.steps.append("ADD {} /build/".format(context_file))
        container_path = os.path.join('/build/', context_file)
        self.steps.append(
            "RUN pip3 install --upgrade -r {content}".format(content=container_path)
        )
