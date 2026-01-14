import sys
sys.path.append('./')
import jwt
import os
from datetime import datetime, timedelta,UTC
import json
import logging
from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict

from model.data_model import *
from db_management.database import DatabaseWrapper
from datetime import datetime
from utils.config import boto_sess,role,default_bucket,sagemaker_session,DEFAULT_ENGINE,DEFAULT_REGION
from logger_config import setup_logger
database = DatabaseWrapper()
logger = setup_logger('login.py',level=logging.INFO)


def create_token(payload):
    return jwt.encode(
        {
            "payload": payload,
            "exp": datetime.now(UTC)+ timedelta(hours=168)
        },
        os.environ.get("TOKEN_KEY","ssdfdamopwe2"),
        algorithm="HS256"
    )
    

def login_auth(username:str,password:str):
    logger.info(f"{username} is loging  in")
    
    status = None
    error = ''
    token = ''
    groupname = ''
    try:
        result = database.query_users(username)
        print(result)
        if result is None:
            logger.info(f"{username} login failed, no user found")
            status = False
            error = 'login failed, no user found'
        else:
            pwd,groupname = result
            if pwd == password:
                logger.info(f"{username} login success")
                status = True
                token = create_token({"username":username,"group":groupname})
            else:
                logger.info(f"{username} login faild, password incorrect")
                status = False
                error = 'login faild, password incorrect'
        
    except Exception as e:
        logger.error(f"{username} login failed, {e}")
        status = False
        error = 'login failed due to internal error'
        
    return  {
        "status": status,
        "error":error,
        "isAuthorized":status,
        "token": token,
        "username":username,
        "groupname":groupname,
        "company":"default"
    }