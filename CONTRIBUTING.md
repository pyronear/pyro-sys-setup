# Contributing to pyro-sys-setup

Everything you need to know to contribute efficiently to the project.

Whatever the way you wish to contribute to the project, please respect the [code of conduct](CODE_OF_CONDUCT.md).


## Continuous Integration

This project uses the following integrations to ensure proper codebase maintenance:

- [Github Worklow](https://help.github.com/en/actions/configuring-and-managing-workflows/configuring-a-workflow) - run jobs for package build and coverage

## Issues

Use Github [issues](https://github.com/pyronear/pyro-sys-setup/issues) for feature requests, or bug reporting. When doing so, use issue templates whenever possible and provide enough information for other contributors to jump in.

## Code contribution

In order to contribute to  project, we will first **set up the development environment**, then describe the **contributing workflow**.

* [Project Setup](#project-setup)

    _How to set up a forked project and install its dependencies in a well-encapsulated development environment_
    1. [Create a virtual environment](#create-a-virtual-environment)
    2. [Fork the project](#fork-the-repository)
* [Contributing workflow](#contributing-workflow)

   _How to pull remote changes/new contributions and push your contributions to the original project_

* [Code & commit guidelines](#commits)

### Project Setup
---
In order to enable every one to fluently contribute to the project, we are going
to set up the project properly following some steps:
1. **Fork the project** to be able to start working on a local copy of the project

#### 1. Fork the repository
We are going to get a local copy of the remote project (_fork_) and set remotes so we stay up to date to recent contributions.

1. Create a fork by clicking on the **fork button** on the current repository page
2. Clone _your_ fork locally.
```shell
# change directory to one for the project
cd /path/to/local/pyronear/project/

# clone your fork. replace YOUR_USERNAME accordingly
git clone https://github.com/YOUR_USERNAME/pyro-sys-setup.git

# cd to pyro-sys-setup
cd pyro-sys-setup
```

3. Set remotes to original project and merge new contributions onto master.
```shell
# add the original repository as remote repository called "upstream"
git remote add upstream https://github.com/pyronear/pyro-sys-setup.git

# verify repository has been correctly added
git remote -v

# fetch all changes from the upstream repository
git fetch upstream

# switch to the master branch of your fork
git checkout master

# merge changes from the upstream repository into your fork
git merge upstream/master
```

4. install the project dependencies (if exists)
```shell
# install dependencies
pip install -r requirements.txt

# install current project in editable mode,
# so local changes will be reflected locally (ie:at import)
pip install -e .
```



### Contributing workflow
---
Once the project is well set up, we are going to detail step by step a usual contributing workflow.

1.  Merge recent contributions onto master (do this frequently to stay up-to-date)
```shell
# fetch all changes from the upstream repository
git fetch upstream

# switch to the master branch of your fork
git checkout master

# merge changes from the upstream repository into your fork
git merge upstream/master
```

Note: Since, we are going to create features on separate local branches so they'll be merged onto **original project remote master** via pull requests, we may use **pulling** instead of fetching & merging. This way our **_local_ master branch** will reflect **_remote_ original project**. We don't expect to make changes on local master in this workflow so no conflict should arise when merging:
```shell
# switch to local master
git checkout master

#  merge remote master of original project onto local master
git pull upstream/master
```

2. Create a local feature branch to work on

```shell
# Create a new branch with the name of your feature
git checkout -b pioneering-feature-branch
```

3. Commit your changes (remember to add unit tests for your code). Feel free to interactively rebase your history to improve readability. See [Commits section](#commits) to follow guidelines.

4. Rebase your feature branch so that merging it will be a simple fast-forward that won't require any conflict resolution work.
```shell
# Switch to feature branch
git checkout pioneering-feature-branch

# Rebase on master
git rebase master
```

5. Push your changes on remote feature branch.
```shell
git checkout pioneering-feature-branch

# Push first time (we create remote branch at the same time)
git push -u origin pioneering-feature-branch

# Next times, we simply push commits
git push origin
```

6. When satisfied with your branch, open a [PR](https://help.github.com/en/articles/creating-a-pull-request-from-a-fork) from your fork in order to integrate your contribution to original project.

### Commits

- **Code**: ensure to provide docstrings to your Python code. In doing so, please follow [Google-style](https://sphinxcontrib-napoleon.readthedocs.io/en/latest/example_google.html) so it can ease the process of documentation later.
- **Commit message**: please follow [Udacity guide](http://udacity.github.io/git-styleguide/)