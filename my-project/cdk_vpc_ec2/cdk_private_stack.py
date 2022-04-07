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
        instance1 = ec2.Instance(self, "MPB-Instance-1",
            instance_type=ec2.InstanceType("t3.nano"),
            machine_image=linux_ami,
            vpc = vpc,
        )

        clusterWithASG = ecs.Cluster(
            self, 'MPB-EcsClusterWithASG',
            vpc=vpc
        )

        clusterWithoutASG = ecs.Cluster(
            self, 'MPB-EcsClusterWithoutASG',
            vpc=vpc
        )

        # Create Task Definition
        task_definition = ecs.FargateTaskDefinition(
            self, "MPB-TaskDef")
        
        container = task_definition.add_container(
            "web",
            image=ecs.ContainerImage.from_registry("amazon/amazon-ecs-sample"),
            memory_limit_mib=256
        )
        port_mapping = ecs.PortMapping(
            container_port=80,
            host_port=80,
            protocol=ecs.Protocol.TCP
        )
        container.add_port_mappings(port_mapping)

        non_scaled_service = ecs.FargateService(self, "Service", cluster=clusterWithoutASG, task_definition=task_definition)

        # Create Fargate Service
        scaled_service = ecs.FargateService(
            self, "sample-app",
            cluster=clusterWithASG,
            task_definition=task_definition
        )
        
        scalableTarget = scaled_service.auto_scale_task_count(
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

        # Create ALB
        lb = elbv2.ApplicationLoadBalancer(
            self, "MPB-ALB",
            vpc=vpc,
            internet_facing=True
        )
        listener8080 = lb.add_listener(
            "PublicListener8080",
            port=8080,
            protocol=elbv2.ApplicationProtocol.HTTP,
            open=True
        )
        listener8081 = lb.add_listener(
            "PublicListener8081",
            port=8081,
            protocol=elbv2.ApplicationProtocol.HTTP,
            open=True
        )

        health_check = elbv2.HealthCheck(
            interval=Duration.seconds(60),
            path="/health",
            timeout=Duration.seconds(5)
        )

        # Attach ALB to ECS Service
        listener8080.add_targets(
            "ScaledECS",
            port=80,
            targets=[scaled_service],
            health_check=health_check,
        )

        # Attach ALB to ECS Service
        listener8081.add_targets(
            "NonScaledECS",
            port=80,
            targets=[non_scaled_service],
            health_check=health_check,
        )

        CfnOutput(
            self, "LoadBalancerDNS",
            value=lb.load_balancer_dns_name
        )
