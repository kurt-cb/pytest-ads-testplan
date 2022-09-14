
Pytest plugin to support Azure Test Plan updating for test cases

Overview
========
This pytest plugin will create an Azure Test Run and append TestResults to the test run as the tests are executed on a pipeline execution of a pytest test run.

This plugin is not ment to work with other reporting plugins like pytest-nunit and pytest-azurepipelines.  Using this test with those plugins will cause duplicate test results to be reported on the pipeline.

Unlike the pytest-azurepipeline plugin, this plugin does not use NUnit to generate a report, then process the report.  Instead, it upates the running tests as they complete.  Therefore, a long running test can have it's progress tracked in Azure Test Runs

Limitations
===========
The tests must all be under the same TestPlan (defined by the plan id)

Each test that will be reported needs to define an ADS suite id and an ADS Test case id (test case work item).

The plugin will scan the test suite for the TestCase, and if found, will add test results for the test point id that matches the test case id defined in the test.

Example
=======

Assuming your org is "TestOrg" and your Project is "TestProject" and your Test Plan ID is 123456

Source code for test case with markings for an ADS test case. Note the suite_id and test_case id are required, the revision is optional and defaults to 1.  It is possible to have multiple test cases and test suites in a single test.  In such a case, the test results will be repeated for each suite_id and test case.  If the test case is not in the suite, then the results will not be reported.

``
@pytest.mark.regress_nightly
@pytest.mark.regress_smoke
@pytest.mark.suite_id("112233")
@pytest.mark.test_case("445556")
@pytest.mark.revision("1")
def test_ads_integration_fail(logger):
    logger.info("This is a test of regression fail")
    assert False
``

From the ADS pipeline, execute this command (bash script pipeline step)

pytest -m regress_nightly --adsinfo=TestOrg,TestProject,123456

The SuiteID must contain a test point with a matching test case, as a test point, in it.  The plugin will search the Suite for the work item, and if found, extract it's description and create a test result for the item.

Tests that are in error (no test case test point in suite) will not be reported

Run Tests outside of azure pipelines
====================================
You can use the plugin outside of an Azure Pipeline, however you would need to use your ADS personal access token (normally provided in the pipeline environment)

``
export SYSTEM_ACCESSTOKEN={token}

pytest -m regress_nightly --adsinfo=TestOrg,TestProject,123456
``

This will use your credentials instead of pipeline credentials and generate a test run that is not attached to a pipeline build.

