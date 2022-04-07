#!/usr/bin/env python3

from aws_cdk import App, Environment

from cdk_vpc_ec2.cdk_vpc_stack import CdkVpcStack
from cdk_vpc_ec2.cdk_private_stack import CdkPrivateStack
from cdk_vpc_ec2.cdk_rds_stack import CdkRdsStack

app = App()

vpc_stack = CdkVpcStack(app, "cdk-vpc")
private_stack = CdkPrivateStack(app, "cdk-private",
                        vpc=vpc_stack.vpc)
rds_stack = CdkRdsStack(app, "cdk-rds",
                        vpc=vpc_stack.vpc,
                        private_security_groups=[private_stack.private_security_group])

app.synth()
