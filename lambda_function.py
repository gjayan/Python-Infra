import json


def lambda_handler(event, context):
    content = '''
        <html>
        <h1> Hello World </h1>
        </html>
    '''

    response = {
        "statusCode": 200,
        "body": content,
        "headers": {"Content-Type": "text/html", },
    }
    return response
