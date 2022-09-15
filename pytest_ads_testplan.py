#/usr/bin/env python3

#
# This file is part of the ptest_ads_testplan distribution
# Copyright (c) 2022 Itron Inc
#
# Credits as a derivitive work from pytest-ntest, an MIT licenced codebase
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
#

"""
This is a Pytest plugin that supports creating a test run on AzureDevops and populating
test results into the test run as test cases complete.

"""
import os
import datetime
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
from azure.devops.v5_1.test.models import TestCaseResult,TestRun, TestSuite, TestPlan, WorkItemReference, TestMessageLogDetails
import logging
import pytest
import sys
import socket
import warnings

log = logging.getLogger(__name__)
local_timezone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo

def pytest_addoption(parser):
    group = parser.getgroup("pytest_ads_testplan")
    group.addoption(
        "--adsinfo",
        action="store",
        default=None,
        help="Set the Azure Test Plan info.  this needs to be '{org},{project},{planid}",
    )
    group.addoption(
        "--ads_build_id",
        action="store",
        default=None,
        help="Set the Azure build id.  Usually this comes from pipeline environment with DOWNLOADPIPELINEARTIFACT_BUILDNUMBER",
    )

@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    if report.when == "call":
        fixture_extras = getattr(item.config, "extras", [])
        plugin_extras = getattr(report, "extra", [])
        report.extra = fixture_extras + plugin_extras

class AdsTestProgress(object):
    """
    Class to keep track of ADS test run information needed for reporting """
    def __init__(self, item, project, test_plan_id, test_run, connection):
        # extract the ADS markers
        self.suite_id = [mark.args[0] for mark in item.iter_markers(name="suite_id")]
        self.test_case_id = [mark.args[0] for mark in item.iter_markers(name="test_case")]
        self.revision = [mark.args[0] for mark in item.iter_markers(name="revision")]
        self.r = {}
        self.nodeid = item.nodeid
        self.test_client = connection.clients.get_test_client()
        self.work_client = connection.clients.get_work_item_tracking_client()
        self.build_client = connection.clients.get_build_client()
        self.project = project
        self.test_plan_id = test_plan_id
        self.test_run = test_run
        self.run_id = str(self.test_run.id)

        self.test_run = test_run


    def test_setup(self, testreport):
        """ called at test setup time,  record information and create the ADS TestCaseResult
            and attach to the test run
        """
        r = self.r
        r.update( {
            "setup-report": testreport,
            "call-report": None,
            "teardown-report": None,
            "path": testreport.fspath,
            "properties": {
                "python-version": sys.version,
                "fspath": testreport.fspath,
            },
            "attachments": None,
            "error": "",
            "stack-trace": "",
            "name": "test_prefix_" + testreport.nodeid,
        })
        r["start"] = datetime.datetime.now(local_timezone)  # Will be overridden if called

        if testreport.outcome == "skipped":
            log.debug("skipping : {0}".format(testreport.longrepr))
            if isinstance(testreport.longrepr, tuple) and len(testreport.longrepr) > 2:
                r["error"] = testreport.longrepr[2]
                r["stack-trace"] = "{0}::{1}".format(
                    testreport.longrepr[0], testreport.longrepr[1]
                )
            elif hasattr(testreport.longrepr, "traceback"): # Catches internal ExceptionInfo type
                r["error"] = str(testreport.longrepr)
                r["stack-trace"] = str(testreport.longrepr.traceback)
            else:
                r["error"] = testreport.longrepr
            return

        start_date =  datetime.datetime.now(local_timezone).isoformat()
        self.test_case_result = []
        count = 0

        warnings.filterwarnings("ignore", category=DeprecationWarning)

        for test_case in self.test_case_id:
            for suite_id in self.suite_id:
                try:
                    revision = "1" if len(self.revision) < 1 else self.revision[0]
                    points = self.test_client.get_points(self.project, self.test_plan_id, suite_id)
                    point = None
                    for p in points:
                        if p.test_case.id == test_case:
                            point = p

                    if not point:
                        log.warning("suite id %s does not contain test case %s as a test point.  Test results lost", suite_id, test_case)
                        continue

                    count = count + 1
                    # retrieve the test case to get the work item information
                    work = self.work_client.get_work_item(test_case)
                    title = work.fields['System.Title']
                    result = TestCaseResult(
                        test_case=WorkItemReference(id=test_case),
                        test_point=point,
                        test_suite=TestSuite(id=suite_id),
                        test_plan=TestPlan(id=self.test_plan_id),
                        test_run=self.test_run,
                        started_date=start_date,
                        state="InProgress",
                        test_case_revision=revision,
                        test_case_title=title,
                        #run_by=test_run.owner
                        )
                    added = self.test_client.add_test_results_to_test_run([result], self.project, self.run_id)
                    self.test_case_result.append(added[0])

                except DeprecationWarning as e:
                    log.warning(e)
                    pass
                except Exception as e:
                    log.warning("Error occurred processing test suite %s: %s", suite_id, e)
        if not count:
            log.error("Test case does not contain any matching Test Plan information.  Verify suite_id and test_case are set correctly")

    # this is called AFTER the test has completed
    def test_call(self, testreport):
        r = self.r
        r["call-report"] = testreport
        r["error"] = testreport.longreprtext
        #r["stack-trace"] = self.nunit_xml._getcrashline(testreport)
        r["properties"].update(testreport.user_properties)
        r["stop"] = datetime.datetime.now(local_timezone)
        r["duration"] = (
            (r["stop"] - r["start"]).total_seconds() if r["call-report"] else 0
        )  # skipped.
        r["teardown-report"] = testreport
        if r["setup-report"].outcome == "skipped":
            r["outcome"] = "skipped"
        elif r["setup-report"].outcome == "failed":
            r["outcome"] = "failed"
        elif "failed" in [r["call-report"].outcome, testreport.outcome]:
            r["outcome"] = "failed"
        else:
            r["outcome"] = "passed"
        r["stdout"] = testreport.capstdout
        r["stderr"] = testreport.capstderr
        r["reason"] = testreport.caplog

        for results in self.test_case_result:
            project = self.project
            run_id = self.run_id
            results.outcome = r["outcome"]
            results.error_message = r["reason"]
            results.completed_date = datetime.datetime.now(local_timezone).isoformat()
            results.computer_name = socket.gethostname()
            results.automated_test_id = self.nodeid
            results.duration_in_ms = float(r['duration'])*1000
            results.stack_trace = r["stack_trace"] if "stack_trace" in r else None
            results.state = "Completed"

            try:
                self.test_client.update_test_results([results], project, run_id)
            except Exception as e:
                log.info("Error updating test_result: %s",e)

    def test_teardown(self, testreport):
        r = self.r


class AdsTestPlugin(object):
    """ Open a TestRun Object, and add tests as they are executed """
    def __init__(self, personal_access_token, org, project, plan):
        organization_url = f'https://dev.azure.com/{org}'
        # Create a connection to the org
        credentials = BasicAuthentication('', personal_access_token)
        connection = Connection(base_url=organization_url, creds=credentials)
        self.project = project
        self.connection = connection
        self.organization_url = organization_url
        self.test_plan_id = plan
        self.test_client = connection.clients.get_test_client()
        self.build_client = connection.clients.get_build_client()
        self.cases = {}



    def pytest_sessionstart(self, session):
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        bld_id = os.getenv("DOWNLOADPIPELINEARTIFACT_BUILDNUMBER")
        self.build_number="private build"
        if bld_id:
            build = self.build_client.get_build(self.project, bld_id)
            print("Build Artifact: ", build)
            self.build_number = build.build_number
        else:
            build = None # detatched test run

        # now, we can create the test run and update it as we go
        started = datetime.datetime.now(local_timezone).isoformat()
        run = TestRun(
            build=build,
            name="pytest regression results - " + started, is_automated=True,
            started_date=datetime.datetime.now(local_timezone).isoformat(),
            plan=TestPlan(id=self.test_plan_id),
            )

        self.test_run = self.test_client.create_test_run(run,self.project)
        logging.info("Test run %s started.\nUrl: %s/%s/_testManagement/runs?_a=runCharts&runId=%s", self.test_run.id, self.organization_url, self.project, self.test_run.id)
        self.run_id = str(self.test_run.id)

        run.started_date = datetime.datetime.now(local_timezone).isoformat()
        run.state = "InProgress"

        # update the test run and set the start date and state
        self.run = self.test_client.update_test_run(run, self.project, self.run_id)

    def pytest_sessionfinish(self, session):
        # notify ADS that test session is complete
        warnings.filterwarnings("ignore", category=DeprecationWarning)
        self.run.completed_date = datetime.datetime.now(local_timezone).isoformat()
        self.run.state = "Completed"
        self.test_client.update_test_run(self.run, self.project, self.run_id)
        for k,v in self.cases.items():
            del v
        self.cases = None
        del self.test_client
        del self.build_client
        del self.connection


    def pytest_runtest_setup(self, item):
        """ create the progress context """
        r = AdsTestProgress(item,  self.project, self.test_plan_id, self.test_run, self.connection)
        self.cases[item.nodeid] =  r

    def pytest_runtest_logreport(self, report):
        """ dispatch report based on stage to the appropriate progress context """

        # note, when used in conjunction with
        if report.nodeid in self.cases:
            r = self.cases[report.nodeid]
            if report.when == "setup":
                log.debug("setup")
                r.test_setup(report)
            elif report.when == "call":
                log.debug("call")
                r.test_call(report)
            elif report.when == "teardown":
                log.debug("teardown")
                r.test_teardown(report)
            else:
                log.debug(report)

def pytest_configure(config):
    personal_access_token = os.getenv('SYSTEM_ACCESSTOKEN')
    # system access token must be selected in pipeline to use this plugin
    if personal_access_token is None:
        return

    if hasattr(config.option, 'adsinfo'):
        info = config.option.adsinfo
        if info:
            (org, project, plan) = info.split(',')
            config._ads_test = AdsTestPlugin(personal_access_token, org, project, plan)
            config.pluginmanager.register(config._ads_test, 'ads_testplan_plugin')

def pytest_unconfigure(config):
    ads = getattr(config, "_ads_test", None)
    if ads:
        del config._ads_test
        config.pluginmanager.unregister(ads)


