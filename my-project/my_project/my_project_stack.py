from aws_cdk import CfnOutput, Stack, Duration
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_rds as rds
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

class MyProjectStack(Stack):

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # The code that defines your stack goes here

        vpc = ec2.Vpc(self, "VPC",
                           max_azs=3,
                           cidr="10.10.0.0/16",
                           # configuration will create 3 groups in 2 AZs = 6 subnets.
                           subnet_configuration=[ec2.SubnetConfiguration(
                               subnet_type=ec2.SubnetType.PUBLIC,
                               name="Public",
                               cidr_mask=24
                           ), ec2.SubnetConfiguration(
                               subnet_type=ec2.SubnetType.PRIVATE_WITH_NAT,
                               name="Private",
                               cidr_mask=24
                           ), ec2.SubnetConfiguration(
                               subnet_type=ec2.SubnetType.PRIVATE_ISOLATED,
                               name="DB",
                               cidr_mask=24
                           )
                           ],
                           # nat_gateway_provider=ec2.NatProvider.gateway(),
                           nat_gateways=3,
                           )

        
        private_security_group = ec2.SecurityGroup(self, "MPB-PrivateGroup",
            vpc=vpc
        )

        alb_security_group = ec2.SecurityGroup(self, "MPB-ALB-SG",
            vpc=vpc
        )

        private_security_group.add_ingress_rule(
            peer = alb_security_group,
            connection = ec2.Port.tcp(9000),
            description = "Allow ALB in"
        )

        cluster = rds.DatabaseCluster(self, "MPB-Database",
            engine=rds.DatabaseClusterEngine.aurora_postgres(version = rds.AuroraPostgresEngineVersion.VER_13_4),
            default_database_name="mpb",
            instance_props=rds.InstanceProps(
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_group_name="DB")
            )
        ) 

        for sg in [private_security_group]:
            cluster.connections.allow_default_port_from(sg, "EC2 Autoscaling Group access Aurora")


        user_data_webserver = ec2.UserData.for_linux()
        user_data_webserver.add_commands("sudo dnf install httpd")
        user_data_webserver.add_commands("sudo systemctl enable --now httpd")

        # Instance
        instance1 = ec2.Instance(self, "MPB-Instance-1",
            instance_type=ec2.InstanceType("t3.nano"),
            machine_image=linux_ami,
            user_data = user_data_webserver,
            security_group = private_security_group,
            vpc = vpc,
        )

        instanceTarget1 = targets.InstanceTarget(instance=instance1)

        instance2 = ec2.Instance(self, "MPB-Instance-2",
            instance_type=ec2.InstanceType("t3.nano"),
            machine_image=linux_ami,
            user_data = user_data_webserver,
            security_group = private_security_group,
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

        ecs_asg = autoscaling.AutoScalingGroup(
            self, "MPB-ASG-ECS",
            instance_type=ec2.InstanceType("t2.micro"),
            machine_image=ecs.EcsOptimizedImage.amazon_linux2(),
            vpc=vpc,
        )
        capacity_provider = ecs.AsgCapacityProvider(self, "AsgCapacityProvider",
            auto_scaling_group=ecs_asg
        )
        clusterWithASG.add_asg_capacity_provider(capacity_provider)

        # Create Task Definition
        task_def_sample = ecs.FargateTaskDefinition(
            self, "MPB-TaskDef-Sample",
            cpu=1024,
            memory_limit_mib=2048
        )

        container_sample = task_def_sample.add_container(
            "sonarqube",
            image=ecs.ContainerImage.from_registry("amazon/amazon-ecs-sample"),
            memory_limit_mib=256,
        )


        port_mapping_sample = ecs.PortMapping(
            container_port=80,
            host_port=80,
            protocol=ecs.Protocol.TCP
        )
        container_sample.add_port_mappings(port_mapping_sample)


        # Create Task Definition
        task_def_sonar = ecs.Ec2TaskDefinition(
            self, "MPB-TaskDef-Sonar",
            network_mode=ecs.NetworkMode.AWS_VPC
            # cpu=2048,
            # memory_limit_mib=8192
        )

        container_sonar = task_def_sonar.add_container(
            "sonarqube",
            image=ecs.ContainerImage.from_registry("sonarqube:8.9.8-community"),
            memory_limit_mib=2048,
            command=["-Dsonar.search.javaAdditionalOpts=-Dnode.store.allow_mmap=false"],
            environment = {
                "SONAR_JDBC_USERNAME": "postgres",
                "SONAR_JDBC_PASSWORD": cluster.secret.secret_value_from_json("password").to_string(),
                "SONAR_JDBC_URL": "jdbc:postgresql://" + cluster.secret.secret_value_from_json("host").to_string() + ":" + cluster.secret.secret_value_from_json("port").to_string() + "/mpb",
            },
            logging = ecs.AwsLogDriver(stream_prefix = "myapp")
        )

        port_mapping_sonar = ecs.PortMapping(
            container_port=9000,
            host_port=9000,
            protocol=ecs.Protocol.TCP
        )
        container_sonar.add_port_mappings(port_mapping_sonar)


        non_scaled_service = ecs.FargateService(
            self, "MPB-NonScaled-Service",
            cluster=clusterWithoutASG,
            task_definition=task_def_sample,
            vpc_subnets=ec2.SubnetSelection(subnet_group_name="Private"),
            security_groups = [private_security_group],
        )

        # # Create Service
        # scaled_service = ecs.Ec2Service(
        #     self, "MPB-Scaled-Service",
        #     cluster=clusterWithASG,
        #     task_definition=task_def_sonar,
        #     vpc_subnets=ec2.SubnetSelection(subnet_group_name="Private"),
        #     security_groups = [private_security_group],
        # )
        
        # scalableTarget = scaled_service.auto_scale_task_count(
        #     min_capacity = 1,
        #     max_capacity = 3
        # )

        # scalableTarget.scale_on_schedule('DaytimeScaleDown',
        #     schedule = appscaling.Schedule.cron(hour = "8", minute = "0"),
        #     min_capacity = 1,
        # )

        # scalableTarget.scale_on_schedule('EveningRushScaleUp',
        #     schedule = appscaling.Schedule.cron(hour = "20", minute = "0"),
        #     min_capacity = 2,
        # )

        # Create ALB
        lb = elbv2.ApplicationLoadBalancer(
            self, "MPB-ALB",
            vpc=vpc,
            internet_facing=True,
            security_group = alb_security_group
        )
        # listener8080 = lb.add_listener(
        #     "PublicListener8080",
        #     port=8080,
        #     protocol=elbv2.ApplicationProtocol.HTTP,
        #     open=True
        # )
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
        # listener8080.add_targets(
        #     "ScaledECS",
        #     port=80,
        #     targets=[scaled_service],
        #     health_check=health_check,
        # )

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
