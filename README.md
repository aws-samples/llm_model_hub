# Model Hub
Model Hub V2是提供一站式的模型微调，部署，调试的无代码可视化平台，可以帮助用户快速验证微调各类开源模型的效果，方便用户快速实验和决策，降低用户微调大模型的门槛。详情请见[飞书使用说明](https://amzn-chn.feishu.cn/docx/QniUdr7FroxShfxeoPacLJKtnXf)

# 请选用以下方式部署：
# 1.自动化部署(暂不支持中国区)
- 进入CloudFormation创建一个stack,选择上传部署文件[cloudformation-template.yaml](./cloudformation-template.yaml)
![alt text](./assets/image-cf1.png)
- 填入一个stack名，例如modelhub, 和HuggingFaceHubToken(可选)
![alt text](./assets/image-cf2.png)
- 一直下一步，直到勾选确认框，然后提交
![alt text](./assets/image-cf3.png)
- 配置完成后，等待stack创建完成，从Stack output栏找到PublicIP地址，然后访问http://{ip}:3000访问modelhub,默认用户名demo_user
![alt text](./assets/image-cf6.png)
- 密码获取：进入AWS System Manager->Parameter Store服务控制台，可以看到多了一个/modelhub/RandomPassword,进入之后打开Show decrypted value开关，获取登陆密码，默认用户名是
![alt text](./assets/image-cf5.png)
- ⚠️注意，stack显示部署完成之后，启动的EC2还需要8-10分钟自动运行一些脚本，如果不行，请等待8-10分钟，然后刷新页面
![alt text](./assets/image-cf4.png)

# 2.手动部署（中国区）
## 1.环境安装
- 硬件需求：一台ec2 Instance, m5.xlarge, 200GB EBS storage
- os需求：ubuntu 22.04
- 配置权限：
1. 在IAM中创建一个ec2 role :adminrole-for-ec2.
- select trust type: AWS service, service: EC2, 
- 添加以下2个服务的权限，AmazonSageMakerFullAccess， CloudWatchLogsFullAccess
- ![alt text](./assets/image_iamrole.png)
- ![alt text](./assets/image_iamrole2.png)
- ![alt text](./assets/image_iamrole3.png)
- 把ec2 instance attach到role
- ![alt text](./assets/bindrole.png)  


2. 创建一个AmazonSageMaker service role: sagemaker_exection_role
![alt text](./assets/image-1.png)
![alt text](./assets/image-2.png)

- 找到刚才的role，创建一个inline policy
- ![alt text](./assets/image-3.png)
- ![alt text](./assets/image-4.png)
- 注意，如果是非中国区手动创建，需要把 "arn:aws-cn:s3:::*"改成 "arn:aws:s3:::sagemaker*"
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "s3:GetObject",
                "s3:PutObject",
                "s3:DeleteObject",
                "s3:ListBucket",
                "s3:CreateBucket"
            ],
            "Resource": [
                "arn:aws-cn:s3:::*"
            ]
        }
    ]
}
```
- ssh 到ec2 instance
- 如果是中国区需要手动下载代码并打包传到ec2中
- 请先在能访问github的环境中执行以下命令下载代码，然后把代码打包成zip文件，上传到ec2服务器的/home/ubuntu/下。
- 使用--recurse-submodule下载代码  
```bash
git clone --recurse-submodule https://github.com/aws-samples/llm_model_hub.git
```
## 2.ssh登陆到ec2服务器，解压到/home/ubuntu/目录
```sh
unzip llm_model_hub.zip
```

## 3.设置环境变量
```sh
export SageMakerRoleArn=<上面步骤创建的sagemaker_exection_role的完整arn,如 arn:aws-cn:iam:1234567890:role/sagemaker_exection_role>
```

## 4.执行脚本
```bash
bash cn-region-deploy.sh
```
大约30之后执行完成，可以在/home/ubuntu/setup.log中查看安装日志。

## 5.访问
- 以上都部署完成后，前端启动之后，可以通过浏览器访问http://{ip}:3000访问前端，/home/ubuntu/setup.log中查看用户名和随机密码
- 如果需要做端口转发，则参考[后端配置](./backend/README.md)中的nginx配置部分


# 如何升级？
- **方法 1**. 下载新的cloudformation 模板进行重新部署，大约12分钟部署完成一个全新的modelhub (此方法以前的job 任务数据会丢失)
- **方法 2**. 
1. 使用一键升级脚本（1.0.6之后支持）：
```bash
cd /home/ubuntu/llm_model_hub/backend/
bash 03.upgrade.sh
```
- **方法 3**. 手动更新：
1. 更新代码, 重新打包byoc镜像
```bash
git pull
git submodule update --remote
cd /home/ubuntu/llm_model_hub/backend/byoc
bash build_and_push.sh 
```
2. 重启服务
```bash
pm2 restart all
```
4. 更新完成