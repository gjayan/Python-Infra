import boto3
import logging
from botocore.exceptions import ClientError
logger = logging.getLogger()
logging.basicConfig(level=logging.INFO, format='%(asctime)s: %(levelname)s: %(message)s')
import os
import zipfile
import time

lambda_arn = ''
sg_id = ''
tg_arn = ''
lb_dns_url = ''
api_invoke_url = ''

lambda_client = boto3.client('lambda', region_name='ap-south-1')
ec2_client = boto3.client('ec2', region_name='ap-south-1')
elb_client = boto3.client('elbv2', region_name='ap-south-1')
api_gateway_client = boto3.client('apigatewayv2')

def create_lambda_fn(lambda_name):
    with zipfile.ZipFile('lambda_function.zip', 'w') as zipf:
        zipf.write('lambda_function.py')

    # Read the zip file
    with open('lambda_function.zip', 'rb') as f:
        zip_contents = f.read()

    # Create the lambda function
    lambda_response = lambda_client.create_function(
        FunctionName=lambda_name,
        Runtime='python3.8',
        Role='arn:aws:iam::775422423362:role/service-role/gayathri-hello-world-role-reds3x8f',
        Handler='lambda_function.lambda_handler',
        Code={'ZipFile': zip_contents},
        Tags={
            'Name': lambda_name
        }
    )

    lambda_fn_arn = lambda_response['FunctionArn']

    global lambda_arn
    lambda_arn = lambda_fn_arn

    print('The Lambda function ' + lambda_name + ' has been successfully created.')

    # Clean up the zip file
    os.remove('lambda_function.zip')

def create_sg(sg_name):
    security_group_response = ec2_client.create_security_group(
        GroupName=sg_name,
        Description='Security group for ALB',
        VpcId = 'vpc-05099366d11596337',
        TagSpecifications=[
        {
            'ResourceType': 'security-group',
            'Tags': [
                {
                    'Key': 'Name',
                    'Value': sg_name
                }
            ]
        }
    ]
    )

    security_group_id = security_group_response['GroupId']
    global sg_id
    sg_id = security_group_id

    ec2_client.authorize_security_group_ingress(
        GroupId=security_group_id,
        IpPermissions=[
            {
                'IpProtocol': 'tcp',
                'FromPort': 80,
                'ToPort': 80,
                'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
            }
        ]
    )
    print('The Security group ' + sg_name + ' has been created successfully.')

def create_tg(tg_name, lambda_name):
    try:
        target_group_response = elb_client.create_target_group(
            Name=tg_name,
            HealthCheckEnabled=True,
            HealthCheckPath='/testweb',
            TargetType='lambda',
            IpAddressType='ipv4',
            Tags=[
                {
                    'Key': 'Name',
                    'Value': tg_name
                }
            ]
        )
    
        target_group_arn = target_group_response["TargetGroups"][0]['TargetGroupArn']
        global tg_arn
        tg_arn = target_group_arn
        print('The Target group ' + tg_name + ' has been created successfully.')
    
        if lambda_name != '':
        #Permission to invoke lambda function
            lambda_response = lambda_client.add_permission(
                    Action='lambda:InvokeFunction',
                    FunctionName=lambda_name,
                    Principal='elasticloadbalancing.amazonaws.com',
                    StatementId='registerTargetPermission',
            )
            print('Permissions added to invoke lambda')
            print('Attaching the lambda with the Target group ...')

            elb_register_response = elb_client.register_targets(
                   TargetGroupArn= tg_arn,
                    Targets=[
                    {
                        'Id': lambda_arn
                    },
                    ]
                )
            print('The Lambda has been attached successfully with the Target group')

        else:
            print('The lambda to be attached to the target group has not been created')

    except ClientError:
            logger.exception(f'Could not create target group' + tg_name)
            raise
    else:
            return tg_arn

def create_lb(alb_name):
    load_balancer_response = elb_client.create_load_balancer(
        Name=alb_name,
        Subnets=['subnet-05b921d732bb43f0b','subnet-0e793eb0b9abff34f'],
        SecurityGroups=[sg_id],
        Tags=[{
            'Key': 'Name',
            'Value': alb_name
        }]
    )
    load_balancer_arn = load_balancer_response['LoadBalancers'][0]['LoadBalancerArn']
    load_balancer_url = load_balancer_response['LoadBalancers'][0]['DNSName']
    global lb_dns_url
    lb_dns_url = load_balancer_url
    print('The Load Balancer '+ alb_name + ' has been successfully created')
    print('Creating the listener rule for the ALB ...')

    waiter = elb_client.get_waiter('load_balancer_available')
    listener_response = elb_client.create_listener(
        LoadBalancerArn=load_balancer_arn,
        Protocol='HTTP', Port=80,
        DefaultActions=[
            {'Type': 'forward', 'TargetGroupArn': tg_arn}
        ]
    )

    time.sleep(180)
    print('The Listener rule for ALB has been created successfully')
    return load_balancer_response['LoadBalancers'][0]['LoadBalancerArn']

def create_http_api(api_name, api_stage_name):
    api_gateway_response = api_gateway_client.create_api(
    Description='API for Qube',
    DisableExecuteApiEndpoint=False,
    Name=api_name,
    ProtocolType='HTTP',
    RouteSelectionExpression='${request.method} ${request.path}',
    Tags={
        'Name': api_name
    },
    Target='http://' + lb_dns_url,
    )
    
    api_id = api_gateway_response['ApiId']
    api_endpoint = api_gateway_response['ApiEndpoint']


    #Creating Integration
    integration_response = api_gateway_client.create_integration(
    ApiId=api_id,
    ConnectionType='INTERNET',
    Description='Qube API HTTP Integration',
    IntegrationMethod='GET',
    IntegrationType='HTTP_PROXY',
    IntegrationUri='http://'+ lb_dns_url,
    PayloadFormatVersion='1.0',
    TimeoutInMillis=30000,
    )

    integration_id = integration_response['IntegrationId']

    #Creating Route
    route_response = api_gateway_client.create_route(
    ApiId=api_id,
    ApiKeyRequired=False,
    AuthorizationType='NONE',
    RouteKey='GET /',
    Target='integrations/' + integration_id
    )

    route_id = route_response['RouteId']

    #Creating stage
    stage_response = api_gateway_client.create_stage(
    ApiId=api_id,
    AutoDeploy=True,
    DefaultRouteSettings={
        'DetailedMetricsEnabled': False,
    },
    Description='Stage for Qube API',
    StageName=api_stage_name,
    Tags={
        'Name': api_stage_name
    }
    )
    print('The API ' + api_name + ' has been created successfully')

    api_endpoint_url = api_endpoint + '/' + api_stage_name
    global api_invoke_url
    api_invoke_url = api_endpoint_url


#Validation for the resources to be created

def lambda_validation(lambda_name):
    try:
        lambda_response = lambda_client.get_function(
                        FunctionName = lambda_name
        )
        lambda_fn_name = lambda_response['Configuration']['FunctionName']

        if lambda_fn_name:
            print('There is already a Lambda function present with the name ' + lambda_name + '. Hence skipping the infrastructure creation')
            lambda_fn_arn = lambda_response['Configuration']['FunctionArn']
            global lambda_arn
            lambda_arn = lambda_fn_arn

    except ClientError:
        logger.exception(f'Could not find the Lambda function ' + lambda_name)
        print('Creating the lambda function '+ lambda_name + ' ...')
        create_lambda_fn(lambda_name)

def security_group_validation(sg_name):
    try:
        security_group_response = ec2_client.describe_security_groups(
            Filters=[
                {
                    'Name': 'tag:Name',
                    'Values': [sg_name]
                },
            ]
        )

        response = security_group_response['SecurityGroups']
        if response:
            print('There is already a Security group present with the name ' + sg_name + '. Hence skipping the infrastructure creation')
            security_group_id = response[0]['GroupId']
            global sg_id
            sg_id = security_group_id
        else:
            print('Creating the security group ' + sg_name + ' ...')
            create_sg(sg_name)
    except ClientError:
        logger.exception(f'Could not find the Security group ' + sg_name)
        raise

def target_group_validation(tg_name,lambda_name):
    try:
        target_group_response = elb_client.describe_target_groups(
        Names=[tg_name]
        )
        response = target_group_response['TargetGroups']
        if response:
            print('There is already a Target group present with the name ' + tg_name + '. Hence skipping the infrastructure creation')
            target_group_arn = target_group_response['TargetGroups'][0]['TargetGroupArn']
            global tg_arn
            tg_arn = target_group_arn

        else:
            print('Creating the Target group ' + tg_name + ' ...')
            create_tg(tg_name,lambda_name)
    except ClientError:
        logger.exception(f'Could not find the Target group ' + tg_name)
        print('Creating the Target group '+ tg_name + ' ...')
        create_tg(tg_name,lambda_name)
        # raise

def load_balancer_validation(alb_name):
    if tg_arn !='': 
        try:
            load_balancer_response = elb_client.describe_load_balancers(
                Names=[alb_name]
            )
            response = load_balancer_response['LoadBalancers']
            if response:
                print('There is already a Load balancer present with the name ' + alb_name + '. Hence skipping the infrastructure creation')
                load_balancer_url = response[0]['DNSName']
                global lb_dns_url
                lb_dns_url = load_balancer_url            
            else:
                print('Creating the load balancer '+ alb_name + '...')
                create_lb(alb_name)
        except ClientError:
            logger.exception(f'Could not find the Load balancer '+ alb_name)
            print('Creating the load balancer '+ alb_name + ' ...')
            create_lb(alb_name)
    else:
        print('Please create the target group first before creating the load balancer')

def api_gateway_validation(api_name, api_stage_name):
    api_gateway_response = api_gateway_client.get_apis()
    response = api_gateway_response['Items']

    if response and response[0]['Name'] == api_name:
        print('There is already a HTTP API present with the name ' + response[0]['Name'] + '. Hence skipping the infrastructure creation')
        api_endpoint = response[0]['ApiEndpoint']
        api_endpoint_url = api_endpoint + '/' + api_stage_name
        global api_invoke_url
        api_invoke_url = api_endpoint_url

    else:
        print('Could not find the API ' + api_name)
        print('Creating the API '+ api_name + ' ...')
        create_http_api(api_name, api_stage_name)



if __name__ == '__main__':
    print('Please enter the name of the Lambda to be created')
    lambda_name = input()
    lambda_validation(lambda_name)
    print('Please enter the name of the Security group to be created')
    sg_name = input()
    security_group_validation(sg_name)
    print('Please enter the name of the Target group to be created')
    tg_name = input()
    target_group_validation(tg_name, lambda_name)
    print('Please enter the name of the Load balancer to be created')
    alb_name = input()
    load_balancer_validation(alb_name)
    print('Please enter the name of the API to be created')
    api_name = input()
    print('Please enter the name of the API Stage to be created')
    api_stage_name = input()
    api_gateway_validation(api_name, api_stage_name)
    print('The URL to invoke the API is ' + api_invoke_url)
    