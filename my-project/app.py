#!/usr/bin/env python3

from aws_cdk import App, Environment

from my_project.my_project_stack import MyProjectStack

app = App()

my_project = MyProjectStack(app, "MyProjectStack")
# my_project2 = MyProjectStack(app, "MyProjectStack2")

app.synth()
