import aws_cdk.aws_autoscaling as autoscaling
import aws_cdk.aws_ec2 as ec2
import aws_cdk.aws_ecs as ecs
import aws_cdk.aws_s3 as s3
import aws_cdk.aws_elasticloadbalancingv2 as elbv2
import aws_cdk.aws_elasticloadbalancingv2_targets as targets
import aws_cdk.aws_rds as rds
from aws_cdk import CfnOutput, Duration, Stack
from constructs import Construct

linux_ami = ec2.AmazonLinuxImage(generation=ec2.AmazonLinuxGeneration.AMAZON_LINUX_2,
                                 edition=ec2.AmazonLinuxEdition.STANDARD,
                                 virtualization=ec2.AmazonLinuxVirt.HVM,
                                 storage=ec2.AmazonLinuxStorage.GENERAL_PURPOSE
                                 )  # Indicate your AMI, no need a specific id in the region

class MyProjectStack(Stack):

    def __init__(self, scope: Construct, id: str, **kwargs) -> None:
        super().__init__(scope, id, **kwargs)

        # Create VPC (and subnets, IGW, NATs)
        vpc = ec2.Vpc(self, "VPC",
                           max_azs=3,
                           cidr="10.10.0.0/16",
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

        # Add secuity group for Private layer
        private_security_group = ec2.SecurityGroup(self, "MPB-PrivateGroup",
            vpc=vpc
        )

        # Add secuity group for ALB
        alb_security_group = ec2.SecurityGroup(self, "MPB-ALB-SG",
            vpc=vpc
        )

        # Create ALB
        lb = elbv2.ApplicationLoadBalancer(
            self, "MPB-ALB",
            vpc=vpc,
            internet_facing=True,
            security_group = alb_security_group
        )

        # Create RDS Database
        cluster = rds.DatabaseCluster(self, "MPB-Database",
            engine=rds.DatabaseClusterEngine.aurora_postgres(version = rds.AuroraPostgresEngineVersion.VER_13_4),
            default_database_name="mpb",
            instance_props=rds.InstanceProps(
                vpc=vpc,
                vpc_subnets=ec2.SubnetSelection(subnet_group_name="DB")
            )
        ) 

        # Allow SG for Private layer to access the DB
        for sg in [private_security_group]:
            cluster.connections.allow_default_port_from(sg, "EC2 Autoscaling Group access Aurora")


        # Configure User-Data to install httpd on initial startup.
        user_data_webserver = ec2.UserData.for_linux()
        user_data_webserver.add_commands("sudo yum install -y httpd")
        user_data_webserver.add_commands("echo 'Hello World' | tee /var/www/html/health")
        user_data_webserver.add_commands("sudo systemctl enable --now httpd")

        # Build instancess
        instance1 = ec2.Instance(self, "MPB-Instance-1",
            instance_type=ec2.InstanceType("t3a.nano"),
            machine_image=linux_ami,
            user_data = user_data_webserver,
            security_group = private_security_group,
            vpc_subnets=ec2.SubnetSelection(subnet_group_name="Private"),
            vpc = vpc,
        )

        instance2 = ec2.Instance(self, "MPB-Instance-2",
            instance_type=ec2.InstanceType("t3a.nano"),
            machine_image=linux_ami,
            user_data = user_data_webserver,
            security_group = private_security_group,
            vpc_subnets=ec2.SubnetSelection(subnet_group_name="Private"),
            vpc = vpc,
        )

        # Create ECS Cluster for scaling
        clusterWithASG = ecs.Cluster(
            self, 'MPB-EcsClusterWithASG',
            vpc=vpc
        )

        # Create ASG
        ecs_asg = autoscaling.AutoScalingGroup(
            self, "MPB-ASG-ECS",
            instance_type=ec2.InstanceType("t3a.small"),
            machine_image=ecs.EcsOptimizedImage.amazon_linux2(),
            vpc=vpc,
        )
        # Configure ASG as ECS Capacity Provider and attach it to ECS Cluster
        capacity_provider = ecs.AsgCapacityProvider(self, "AsgCapacityProvider",
            auto_scaling_group=ecs_asg
        )
        clusterWithASG.add_asg_capacity_provider(capacity_provider)

        # Create ECS Cluster without scaling
        clusterWithoutASG = ecs.Cluster(
            self, 'MPB-EcsClusterWithoutASG',
            vpc=vpc
        )

        # Create Sample Task Definition
        task_def_sample = ecs.FargateTaskDefinition(
            self, "MPB-TaskDef-Sample",
            cpu=1024,
            memory_limit_mib=2048
        )

        # Create Sample Container
        container_sample = task_def_sample.add_container(
            "MPB-sample",
            image=ecs.ContainerImage.from_registry("amazon/amazon-ecs-sample"),
            memory_limit_mib=256,
        )
        # Configure Port Mapping for Sample Container
        port_mapping_sample = ecs.PortMapping(
            container_port=80,
            host_port=80,
            protocol=ecs.Protocol.TCP
        )
        container_sample.add_port_mappings(port_mapping_sample)


        # Create SonarQube Task Definition
        task_def_sonar = ecs.Ec2TaskDefinition(
            self, "MPB-TaskDef-Sonar",
            network_mode=ecs.NetworkMode.AWS_VPC
        )

        # Create container for SonarQube, configure it to use Postgres RDS
        container_sonar = task_def_sonar.add_container(
            "MPB-sonarqube",
            image=ecs.ContainerImage.from_registry("sonarqube:8.9.8-community"),
            memory_limit_mib=1536,
            command=["-Dsonar.search.javaAdditionalOpts=-Dnode.store.allow_mmap=false"],
            environment = {
                "SONAR_JDBC_USERNAME": "postgres",
                "SONAR_JDBC_PASSWORD": cluster.secret.secret_value_from_json("password").to_string(),
                "SONAR_JDBC_URL": "jdbc:postgresql://" + cluster.secret.secret_value_from_json("host").to_string() + ":" + cluster.secret.secret_value_from_json("port").to_string() + "/mpb",
            },
            logging = ecs.AwsLogDriver(stream_prefix = "myapp")
        )

        # Configure Port Mapping for SonarQube Container
        port_mapping_sonar = ecs.PortMapping(
            container_port=9000,
            host_port=9000,
            protocol=ecs.Protocol.TCP
        )
        container_sonar.add_port_mappings(port_mapping_sonar)

        # Create Service for Sample (using Fargate)
        non_scaled_service = ecs.FargateService(
            self, "MPB-NonScaled-Service",
            cluster=clusterWithoutASG,
            task_definition=task_def_sample,
            vpc_subnets=ec2.SubnetSelection(subnet_group_name="Private"),
            security_groups = [private_security_group],
        )

        # Create Service for SonarQube (using EC2)
        scaled_service = ecs.Ec2Service(
            self, "MPB-Scaled-Service",
            cluster=clusterWithASG,
            task_definition=task_def_sonar,
            vpc_subnets=ec2.SubnetSelection(subnet_group_name="Private"),
            security_groups = [private_security_group],
        )
        
        # Configure listeners for services
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

        # Configure healthchecks for services
        health_check = elbv2.HealthCheck(
            interval=Duration.seconds(60),
            path="/health",
            timeout=Duration.seconds(5)
        )

        health_check_sonar = elbv2.HealthCheck(
            interval=Duration.seconds(60),
            path="/api/system/status",
            timeout=Duration.seconds(5)
        )

        # Attach ALB listeners to ECS Services
        listener8080.add_targets(
            "ScaledECS",
            port=9000,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[scaled_service.load_balancer_target(
                container_name="MPB-sonarqube",
                container_port=9000
            )],
            health_check=health_check_sonar,
        )

        listener8081.add_targets(
            "NonScaledECS",
            port=80,
            targets=[non_scaled_service],
            health_check=health_check,
        )

        # Set up a bucket
        bucket = s3.Bucket(self, "example-bucket",
                           access_control=s3.BucketAccessControl.BUCKET_OWNER_FULL_CONTROL,
                           encryption=s3.BucketEncryption.S3_MANAGED,
                           block_public_access=s3.BlockPublicAccess.BLOCK_ALL)

        CfnOutput(
            self, "LoadBalancerDNS",
            value=lb.load_balancer_dns_name
        )
