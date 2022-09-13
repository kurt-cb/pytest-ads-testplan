# pytest-ads-testplan
Pytest plugin to support Azure Test Plan updating for test cases

Overview
========
This pytest plugin will create an Azure Test Run and append TestResults to the test run as the tests are executed on a pipeline execution of a pytest test run.

This plugin is not ment to work with other reporting plugins like pytest-nunit and pytest-azurepipelines.  Using this test with those plugins will cause duplicate test results to be reported on the pipeline.

Limitations
===========
The tests must all be under the same TestPlan (defined by the plan id)

Each test that will be reported needs to define an ADS suite id and an ADS Test case id (test case work item).

The plugin will scan the test suite for the TestCase, and if found, will add test results for the test point id that matches the test case id defined in the test.



