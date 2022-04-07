from aws_cdk import CfnOutput, Stack, Duration
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_ecs as ecs
import aws_cdk.aws_ecs_patterns as ecs_patterns
import aws_cdk.aws_elasticloadbalancingv2 as elbv2
import aws_cdk.aws_autoscaling as autoscaling
import aws_cdk.aws_applicationautoscaling as appscaling
from constructs import Construct

ec2_type = "t2.micro"
key_name = "matt2"  # Setup key_name for EC2 instance login
linux_ami = ec2.AmazonLinuxImage(generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX,
                                 edition=ec2.AmazonLinuxEdition.STANDARD,
                                 virtualization=ec2.AmazonLinuxVirt.HVM,
                                 storage=ec2.AmazonLinuxStorage.GENERAL_PURPOSE
                                 )  # Indicate your AMI, no need a specific id in the region


class CdkPrivateStack(Stack):

    def __init__(self, scope: Construct, id: str, vpc, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Instance
        instance = ec2.Instance(self, "MPB-Instance-1",
            instance_type=ec2.InstanceType("t3.nano"),
            machine_image=linux_ami,
            vpc = vpc,
        )

        cluster = ecs.Cluster(
            self, 'MPB-EcsClusterWithASG',
            vpc=vpc
        )

        # Create Task Definition
        task_definition = ecs.Ec2TaskDefinition(
            self, "MPB-TaskDef")
        container = task_definition.add_container(
            "web",
            image=ecs.ContainerImage.from_registry("amazon/amazon-ecs-sample"),
            memory_limit_mib=256
        )
        port_mapping = ecs.PortMapping(
            container_port=80,
            host_port=8080,
            protocol=ecs.Protocol.TCP
        )
        container.add_port_mappings(port_mapping)

        # Create Fargate Service
        fargate_service = ecs_patterns.ApplicationLoadBalancedFargateService(
            self, "sample-app",
            cluster=cluster,
            task_image_options={
                'image': ecs.ContainerImage.from_registry("amazon/amazon-ecs-sample")
            }
        )

        fargate_service.service.connections.security_groups[0].add_ingress_rule(
            peer = ec2.Peer.ipv4(vpc.vpc_cidr_block),
            connection = ec2.Port.tcp(80),
            description="Allow http inbound from VPC"
        )

        scalableTarget = fargate_service.service.auto_scale_task_count(
            min_capacity = 1,
            max_capacity = 3
        )

        scalableTarget.scale_on_schedule('DaytimeScaleDown',
            schedule = appscaling.Schedule.cron(hour = "8", minute = "0"),
            min_capacity = 1,
        )

        scalableTarget.scale_on_schedule('EveningRushScaleUp',
            schedule = appscaling.Schedule.cron(hour = "20", minute = "0"),
            min_capacity = 2,
        )

        CfnOutput(
            self, "LoadBalancerDNS",
            value=fargate_service.load_balancer.load_balancer_dns_name
        )
