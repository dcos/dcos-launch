## High-level description (required)

What features does this change enable? / What bugs does this change fix?


## Corresponding tickets (required)

These JIRA ticket(s) must be updated (ideally closed) in the moment this PR lands:

  - [QUALITY-<number>](https://jira.mesosphere.com/browse/QUALITY-<number>) Foo the Bar so it stops Bazzing.


## Related tickets (optional)

Other tickets related to this change

  - [QUALITY-<number>](https://jira.mesosphere.com/browse/QUALITY-<number>) Foo the Bar so it stops Bazzing.


## Related PRs (optional)

Is this change going to be propagated up into dcos-integration-tests in dcos/dcos or another repo? Does this change require changes in dcos-test-utils? Link the corresponding PRs here:


## Checklist for all PRs

  - [ ] Included a test which will fail if code is reverted but test is not. If there is no test please explain here:
  - [ ] **Added or updated any relevant documentation**

[Integration tests](https://teamcity.mesosphere.io/project.html?projectId=DcosIo_DcosLaunch&branch_DcosIo_DcosLaunch=%3Cdefault%3E) were run and

  - [ ] AWS Cloudformation Simple (link to job: )
  - [ ] Azure Resource Manager (link to job: )
  - [ ] Onprem-AWS (link to job: )
  - [ ] Onprem-GCE (link to job: )

**PLEASE FILL IN THE TEMPLATE ABOVE** / **DO NOT REMOVE ANY SECTIONS ABOVE THIS LINE**


## Instructions and review process

**What is the review process and when will my changes land?**

All PRs should have two approved [pull request reviews](https://help.github.com/articles/about-pull-request-reviews/).

Reviewers should be:
* Developers who understand the code being modified.
* Developers responsible for code that interacts with or depends on the code being modified.

It is best to proactively ask for 2 reviews by @mentioning the candidate reviewers in the PR comments area. The responsibility is on the developer submitting the PR to follow-up with reviewers and make sure a PR is reviewed in a timely manner.
