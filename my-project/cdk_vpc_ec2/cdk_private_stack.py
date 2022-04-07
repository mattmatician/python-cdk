from aws_cdk import CfnOutput, Stack, Duration
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_ecs as ecs
import aws_cdk.aws_ecs_patterns as ecs_patterns
import aws_cdk.aws_elasticloadbalancingv2 as elbv2
import aws_cdk.aws_autoscaling as autoscaling
import aws_cdk.aws_applicationautoscaling as appscaling
import aws_cdk.aws_elasticloadbalancingv2_targets as targets
from constructs import Construct

ec2_type = "t2.micro"
key_name = "matt2"  # Setup key_name for EC2 instance login
linux_ami = ec2.AmazonLinuxImage(generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX,
                                 edition=ec2.AmazonLinuxEdition.STANDARD,
                                 virtualization=ec2.AmazonLinuxVirt.HVM,
                                 storage=ec2.AmazonLinuxStorage.GENERAL_PURPOSE
                                 )  # Indicate your AMI, no need a specific id in the region

class CdkPrivateStack(Stack):

    def __init__(self, scope: Construct, id: str, vpc, private_security_group, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        user_data_webserver = ec2.UserData.for_linux()
        user_data_webserver.add_commands("sudo dnf install httpd")
        user_data_webserver.add_commands("sudo systemctl enable --now httpd")

        alb_security_group = ec2.SecurityGroup(self, "MPB-ALB-SG",
            vpc=self.vpc
        )

        private_security_group.add_ingress_rule(
            peer = alb_security_group,
            connection = ec2.Port.tcp(9000),
            description = "Allow ALB in"
        )

        # Instance
        instance1 = ec2.Instance(self, "MPB-Instance-1",
            instance_type=ec2.InstanceType("t3.nano"),
            machine_image=linux_ami,
            user_data = user_data_webserver,
            security_group = self.private_security_group,
            vpc = vpc,
        )

        instanceTarget1 = targets.InstanceTarget(instance=instance1)

        instance2 = ec2.Instance(self, "MPB-Instance-2",
            instance_type=ec2.InstanceType("t3.nano"),
            machine_image=linux_ami,
            user_data = user_data_webserver,
            security_group = self.private_security_group,
            vpc = vpc,
        )

        instanceTarget2 = targets.InstanceTarget(instance=instance2)

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
            self, "MPB-TaskDef",
            cpu=2048,
            memory_limit_mib=8192
        )
        
        container = task_definition.add_container(
            "sonarqube",
            image=ecs.ContainerImage.from_registry("sonarqube:8.9.8-community"),
            memory_limit_mib=2048,
            command=["-Dsonar.search.javaAdditionalOpts=-Dnode.store.allow_mmap=false"],
            environment = {
                "SONAR_JDBC_USERNAME": "admin",
                "SONAR_JDBC_PASSWORD": "password",
                "SONAR_JDBC_URL": "postgresql:///",
            }
        )

        port_mapping = ecs.PortMapping(
            container_port=9000,
            host_port=9000,
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
            internet_facing=True,
            security_group = alb_security_group
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
