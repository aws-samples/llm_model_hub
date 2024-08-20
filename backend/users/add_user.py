import sys
sys.path.append('./')
from db_management.database import DatabaseWrapper
from logger_config import setup_logger
import argparse

database = DatabaseWrapper()

def add_user(username:str, password:str, groupname:str):
    try:
        database.add_user(username, password, groupname)
    except Exception as e:
        print(e)
        return False
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add a new user")
    parser.add_argument("username", help="Username for the new user")
    parser.add_argument("password", help="Password for the new user")
    parser.add_argument("groupname", choices=['admin', 'default'], help="User group (admin or default)")
    
    args = parser.parse_args()

    ret = add_user(args.username, args.password, args.groupname)
    if ret:
        print(f"添加用户成功:{args.username}/{args.password}/{args.groupname}")
    else:
        print("添加用户失败")