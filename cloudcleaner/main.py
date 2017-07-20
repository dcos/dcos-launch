"""Main function and code to bind the various components together to a runable cloud cleaner cli."""
import argparse
import json
import logging
import sys

import jinja2
from pkg_resources import resource_string

import cloudcleaner
import cloudcleaner.common

LOGGING_FORMAT = '[%(asctime)s|%(name)s|%(levelname)s]: %(message)s'


def make_html_report(report):
    """Render an HTML report of the cloudcleaner findings."""
    return jinja2.Template(resource_string(__name__, "report.html.jinja").decode()).render(report)


def write_file(name, contents):
    """Write a file without leaking an fd to Garbage Collection."""
    with open(name, 'w') as f:
        f.write(contents)


def do_main(argument_array):
    """Build the argument parser than run cloudcleaner with the args."""
    logging.basicConfig(format=LOGGING_FORMAT, level=logging.INFO)
    parser = argparse.ArgumentParser()
    parser.add_argument('--be-ruthless', action='store_true')
    parser.add_argument('--key-match', action='store')
    args = parser.parse_args(argument_array)

    dry_run = not args.be_ruthless

    if args.key_match and len(args.key_match) < 5:
        print('To avoid matching to too many key names, use at least 5 characters to match with.')
        sys.exit(1)

    report = cloudcleaner.run(dry_run, args.key_match)

    # Write out a machine-readable report
    write_file("report.json", json.dumps(report, sort_keys=True, indent=4, separators=(',', ':')))

    # Write out a human-readable report
    write_file('cloudcleaner.html', make_html_report(report))

    return report


def main_wrapper(func, *args):
    """Wrap main and catch common exceptions, giving them better error messages."""
    try:
        return func(*args)
    except cloudcleaner.common.UnsafeWithoutEnvVar:
        print("ERROR: THIS_IS_NOT_A_TEST environment variable must be set to "
              "run cloudcleaner. This helps guard against accidentally running "
              "the code on their machine and it calling APIs which could "
              "potentially take out an entire AWS production account.")
        sys.exit(1)


def main():
    """Run cloudcleaner and generate a report. Copy the report to stdout to make things easier in jenkins."""
    report = main_wrapper(do_main, sys.argv[1:])

    # HACK(cmaloney): Write report.json to the screen since in some environments the artifacts
    # aren't available.
    if report:
        print("##### BEGIN report.json #####")
        print(json.dumps(report, sort_keys=True, indent=4, separators=(',', ':')))
        print("##### END report.json #####")
