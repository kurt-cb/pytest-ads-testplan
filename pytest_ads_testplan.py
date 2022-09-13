#/usr/bin/env python3
import pytest
import os
import datetime
from azure.devops.connection import Connection
from msrest.authentication import BasicAuthentication
from azure.devops.v5_1.test.models import TestCaseResult,TestRun, TestSuite, TestPlan, WorkItemReference

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



class AdsTestPlugin:
    """ Open a TestRun Object, and add tests as they are executed """
    def __init__(self, personal_access_token, org, project, plan):
        organization_url = f'https://dev.azure.com/{org}'
        # Create a connection to the org
        credentials = BasicAuthentication('', personal_access_token)
        connection = Connection(base_url=organization_url, creds=credentials)
        self.project = project
        self.test_plan_id = plan
        self.test_client = connection.clients.get_test_client()
        self.work_client = connection.clients.get_work_item_tracking_client()
        self.build_client = connection.clients.get_build_client()

        bld_id = os.getenv("DOWNLOADPIPELINEARTIFACT_BUILDNUMBER")
        self.build_number="private build"
        if bld_id:
            build = self.build_client.get_build(project, bld_id)
            print("Build Artifact: ", build)
            self.build_number = build['build_number']

        # now, we can create the test run and update it as we go
        local_timezone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo
        build = self.build_client.get_build(project, 1376513)
        started = datetime.datetime.now(local_timezone).isoformat()
        run = TestRun(
            build=str(bld_id),
            build_number = self.build_number,
            name="pytest regression results - " + started, is_automated=True,
            started_date=datetime.datetime.now(local_timezone).isoformat(),
            plan=TestPlan(id=self.test_plan_id),
            )

        self.test_run = self.test_client.create_test_run(run,project)
        self.run_id = str(self.test_run.id)

        run.started_date = datetime.datetime.now(local_timezone).isoformat()
        run.state = "InProgress"
        run = self.test_client.update_test_run(run, project, self.run_id)

    def write_case(self, test_id, test_run,test_case, properties):
        try:
            date = test_case['start-time']
            date_time_obj = datetime.datetime.strptime(date, '%Y-%m-%d %H:%M:%S.%f')
            start_date = date_time_obj.isoformat()
            date = test_case['end-time']
            date_time_obj = datetime.datetime.strptime(date, '%Y-%m-%d %H:%M:%S.%f')
            end_date = date_time_obj.isoformat()
            desc = properties.get('description', test_case['name'])
            work_item = str(properties.get('WorkItemId', None))
            suiteId = str(properties.get('SuiteId', None))
            planId = str(properties.get('PlanId', None))
            points = self.test_client.get_points(self.project, planId, suiteId)
            for p in points:
                if p.test_case.id == work_item:
                    point = p

            work = self.work_client.get_work_item(work_item)
            title = work.fields['System.Title']

            result = TestCaseResult(
                test_case=WorkItemReference(id=work_item),
                test_point=point,
                test_suite=TestSuite(id=suiteId),
                test_plan=TestPlan(id=planId),
                test_run=test_run,
                outcome=test_case['result'],
                started_date=start_date,
                state="Completed",
                test_case_revision=properties.get('Revision', "1"),
                test_case_title=title,
                completed_date=end_date,
                duration_in_ms=float(test_case['duration'])*1000,
                )
            print("Test run id: ", test_run.id)
            print("Test result: ", result)
            self.test_client.add_test_results_to_test_run([result], project, run_id)
        except Exception as e:
            print(e)
        return True

    def pytest_runtest_call(self):
        self.create_case()
    def pytest_runtest_logreport(self, report):
        self.write_case(report)


@pytest.mark.trylast
def pytest_configure(config):
    personal_access_token = os.getenv('SYSTEM_ACCESSTOKEN')
    # system access token must be selected in pipeline to use this plugin
    if personal_access_token is None:
        return

    if hasattr(config.option, 'adsinfo'):
        info = config.option.adsinfo
        (org, project, plan) = info.split(',')
        config.pluginmanager.register(AdsTestPlugin(personal_access_token, org, project, plan))


