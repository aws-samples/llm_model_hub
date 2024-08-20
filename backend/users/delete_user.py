
import sys
sys.path.append('./')
from db_management.database import DatabaseWrapper
from logger_config import setup_logger
database = DatabaseWrapper()


def delete_user(username:str):
    try:
        database.delete_user(username)
    except Exception as e:
        print(e)
        return False
    return True

if __name__ == "__main__":
    print("请输入需要删除的用户名:")
    username = input()
    print("确定删除用户吗? Y/N")
    confirm = input()
    if confirm in ['Y','y']:
        ret = delete_user(username)
        if ret:
            print(f"删除用户成功:{username}")
        else:
            print("删除用户失败")