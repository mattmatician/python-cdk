# Sample Deployment using Python aws-cdk

## Getting started

I installed cdk and ran `cdk init` selecting python as my chosen language.

In order to get stated, I consulted this repo:

https://github.com/aws-samples/aws-cdk-examples

for inspiration.

### AZs

In order to use 3 AZs, a specific and supported region is required to be specifed in [app.py](./my-project/app.py)

## VPC

The Vpc construct includes the creation of subnets, routes, IGW and NATs.

We configured three different subnets (per AZ):

* Public
* Private
* DB

## LB

I created one Application Load Balancer.

## RDS Cluster

I created an Amazon Aurora PostGres RDS database ensuring that it used the DB Subnets.
The cluster creates a DB instance per AZ.

## Instances

I created 6 simple EC2 instances using the default Amazon Linux 2 AMI.
I had Apache httpd installed on initial startup using user-data, and a simple Hello World webpage is installed.
This is not available publically.

## ECS Clusters
### Cluster with ASG

I created an ECS Cluster and an auto-scaling group and then configured the ASG to be the ECS Cluster's Capacity provider.
If further services are added then the ASG would provision more EC2 instances.

I chose to use the `sonarqube:8.9.8-community` image in an EC2 service in this cluster, and configured it to use the PostgresSQL RDS cluster as a DB backend that I configured earlier.

After initial deployment, the default username and password of `admin` and `admin` are used to login to the web application.

This can be accessed by surfing to the LB's public DNS name under port **8080** (as this is where the respective listener is configured)

### Cluster without ASG

I created a simple ECS Cluster with no such capacity provider.

For this example I used a sample `amazon/amazon-ecs-sample` image and ran it with Fargate (instead of EC2).

This can be accessed by surfing to the LB's public DNS name under port **8081** (as this is where the respective listener is configured)

## S3 bucket

I created a simple empty S3 bucket.

# Multiple deployments

I was able to deploy the stack twice by instantiating another MyProjectStack in [app.py](./my-project/app.py)

It is worth noting that, by default, an AWS account is limited to just 5 Elastic IPs. This can be requesting it of AWS.

# DR

Cross-region and regular backups could be taken of the RDS Database. In the event of disaster. The deployment could be moved to a different region.

