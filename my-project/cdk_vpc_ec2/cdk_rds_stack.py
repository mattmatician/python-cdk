from aws_cdk import Duration, Stack
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_rds as rds
from constructs import Construct

class CdkRdsStack(Stack):

    def __init__(self, scope: Construct, id: str, vpc, private_security_groups, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        cluster = rds.DatabaseCluster(self, "MPB-Database",
            engine=rds.DatabaseClusterEngine.aurora_postgres(version = rds.AuroraPostgresEngineVersion.VER_13_4),
            instance_props=rds.InstanceProps(
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_group_name="DB")
            )
        ) 

        for sg in private_security_groups:
            cluster.connections.allow_default_port_from(sg, "EC2 Autoscaling Group access Aurora")