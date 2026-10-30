import argparse
import logging
import os
import re
import subprocess
import json
import sys
from typing import List, Dict, Any

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class LicenseComplianceChecker:
    """
    Scans a project's dependencies and lists their licenses, highlighting potential compliance issues.
    """

    def __init__(self, project_path: str, output_format: str = "text"):
        """
        Initializes the LicenseComplianceChecker.

        Args:
            project_path (str): The path to the project directory.
            output_format (str): The format for output (text or json). Defaults to "text".
        """
        self.project_path = project_path
        self.output_format = output_format
        self.dependencies = {}  # type: Dict[str, Dict[str, Any]]

    def _execute_command(self, command: List[str]) -> str:
        """
        Executes a shell command and returns the output.

        Args:
            command (List[str]): The command to execute as a list of strings.

        Returns:
            str: The output of the command.

        Raises:
            subprocess.CalledProcessError: If the command returns a non-zero exit code.
        """
        try:
            # Commands arrive as pip arguments and run through this
            # interpreter's own pip module. A bare "pip" from PATH can
            # belong to a different Python, and then every license in
            # the report describes the wrong environment.
            process = subprocess.run([sys.executable, '-m', 'pip'] + command, cwd=self.project_path, capture_output=True, text=True, check=True)
            return process.stdout.strip()
        except subprocess.CalledProcessError as e:
            logging.error(f"Command failed: {e}")
            raise

    def _get_dependencies(self) -> None:
        """
        Retrieves the list of dependencies for the project.

        A requirements.txt in the project directory names the project's
        own dependencies, so it wins when present. pip freeze is only a
        fallback: it lists whatever is installed in this environment,
        which for an empty project directory is a report about the
        wrong thing. That fallback is kept because a project with no
        manifest has nothing else to go on, and the warning below says
        when it is in use.
        """
        requirements = os.path.join(self.project_path, 'requirements.txt')
        if os.path.isfile(requirements):
            with open(requirements, 'r') as f:
                for raw_line in f:
                    line = raw_line.split('#', 1)[0].strip()
                    if not line or line.startswith('-'):
                        continue
                    package_name = re.split(r'==|>=|<=|~=|!=|>|<|\[|;', line, maxsplit=1)[0].strip()
                    package_version = 'unspecified'
                    if '==' in line:
                        package_version = line.split('==', 1)[1].split(';')[0].strip()
                    if package_name:
                        self.dependencies[package_name] = {'version': package_version}
            return
        logging.warning("No requirements.txt in project path; reporting the current environment from pip freeze instead.")
        try:
            output = self._execute_command(['freeze'])
            for line in output.splitlines():
                if '==' in line:
                    package_name, package_version = line.split('==', 1)
                    self.dependencies[package_name] = {'version': package_version}
        except subprocess.CalledProcessError:
            logging.error("Failed to retrieve dependencies using pip freeze.")
            sys.exit(1)


    def _get_license_info(self, package_name: str) -> None:
        """
        Retrieves license information for a given package using pip show.

        Args:
            package_name (str): The name of the package.
        """
        try:
            output = self._execute_command(['show', package_name])
            license_info = ""
            license_expression = ""
            for line in output.splitlines():
                key, _, value = line.partition(':')
                key = key.strip().lower()
                value = value.strip()
                if key == 'license':
                    license_info = value
                elif key == 'license-expression':
                    license_expression = value
                elif key == 'home-page' and value:
                    # pip prints an empty Home-page for packages that
                    # declare none. Storing that empty string would make
                    # the report print a blank instead of falling back
                    # to UNKNOWN, so only a real value is kept.
                    self.dependencies[package_name]['homepage'] = value
            # PEP 639 packages carry no License line at all: modern pip
            # prints only License-Expression, an SPDX expression such
            # as "Apache-2.0 AND MIT". Without this fallback every such
            # package reported UNKNOWN even though pip had just printed
            # its license. The legacy field wins when it has a value,
            # because it is the only field older packages declare.
            self.dependencies[package_name]['license'] = license_info or license_expression or "UNKNOWN"
        except subprocess.CalledProcessError:
            logging.warning(f"Failed to retrieve license information for {package_name}.")
            self.dependencies[package_name]['license'] = "UNKNOWN"
        except Exception as e:
            logging.error(f"An unexpected error occurred while processing {package_name}: {e}")
            self.dependencies[package_name]['license'] = "UNKNOWN"


    def scan_licenses(self) -> None:
        """
        Scans the licenses of all dependencies.
        """
        self._get_dependencies()
        for package_name in self.dependencies:
            self._get_license_info(package_name)

    def generate_report(self) -> str:
        """
        Generates a report of the license compliance check.

        Returns:
            str: The report in the specified output format.
        """
        if self.output_format == "json":
            return json.dumps(self.dependencies, indent=4)
        else:  # Default to text
            report = "License Compliance Report:\n"
            for package_name, info in self.dependencies.items():
                report += f"\nPackage: {package_name}\n"
                report += f"  Version: {info.get('version', 'UNKNOWN')}\n"
                report += f"  License: {info.get('license', 'UNKNOWN')}\n"
                report += f"  Homepage: {info.get('homepage', 'UNKNOWN')}\n"
            return report

def setup_argparse() -> argparse.ArgumentParser:
    """
    Sets up the argument parser for the command-line interface.

    Returns:
        argparse.ArgumentParser: The argument parser.
    """
    parser = argparse.ArgumentParser(description='Scans a project\'s dependencies and lists their licenses.')
    parser.add_argument('project_path', help='The path to the project directory.')
    parser.add_argument('--output_format', choices=['text', 'json'], default='text',
                        help='The format for the output report (text or json). Defaults to text.')
    parser.add_argument('--log_level', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], default='INFO',
                        help='Set the logging level.')
    return parser

def main() -> None:
    """
    Main function to run the license compliance checker.
    """
    parser = setup_argparse()
    args = parser.parse_args()

    # Set the logging level
    logging.getLogger().setLevel(args.log_level)

    project_path = args.project_path
    output_format = args.output_format

    # Validate input
    if not os.path.isdir(project_path):
        logging.error(f"Invalid project path: {project_path}")
        sys.exit(1)

    checker = LicenseComplianceChecker(project_path, output_format)
    try:
        checker.scan_licenses()
        report = checker.generate_report()
        print(report)  # Output to stdout
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

