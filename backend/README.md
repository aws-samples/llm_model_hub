# 后端环境安装
## 0. 中国区说明（海外区可以跳过）
1. 如果在中国区部署，请先执行以下脚本，修改pip源，docker源。
```bash
bash 0.setup-cn.sh
```

## 1.安装后端环境
1. 进入backend目录,复制env.sample 文件为.env
```bash
cd backend
cp env.sample .env
```
2. 修改编辑.env文件
```bash
vim .env
```
* 1.如果ec2已经绑定了role，则无需填写AK，SK和profile
* 2.修改region为实际region
* 3.修改role为之前在IAM中创建的sagemaker execution role的arn
* 4.修改api_keys为上一级目录中.env中的api key，前后端保持一致
* 5.有些模型(如LLaMA等)需要提供HUGGING_FACE_HUB_TOKEN，请在.env中添加
```bash
AK=
SK=
profile=
region=us-east-1
role=arn:aws:iam::
db_host=127.0.0.1
db_name=llm
db_user=llmdata
db_password=llmdata
api_keys=
HUGGING_FACE_HUB_TOKEN=
WANDB_API_KEY=
WANDB_BASE_URL=
MAX_MODEL_LEN=4096
```

2. 仍然在backend/目录下执行以下命令进行安装
```bash
bash 01.setup.sh
```

- 2.1 打包vllm推理镜像
```bash
cd ~/llm_model_hub/backend/byoc
bash build_and_push.sh
source ../../miniconda3/bin/activate py311
conda activate py311
python3 startup.py 
```

## 2.添加用户
- 仍然在backend/目录下执行以下python脚本命令添加用户
```bash
cd ~/llm_model_hub/backend/
source ../miniconda3/bin/activate py311
conda activate py311
python3 users/add_user.py your_username your_password default
```
请自行添加用户和密码，并保存到安全的位置。


## 3.后台启动进程
- 执行以下命令启动后台进程
```bash
bash 02.start_backend.sh
```
- 以下命令查看后台进程是否启动成功
```bash
pm2 list
```
modelhub是前端进程，modelhub-engine和modelhub-server是后端进程
![alt text](../assets/image-pm2list.png)


## 4.安装nginx（可选）
- 安装nginx
```bash
sudo apt update 
sudo apt install nginx
```

- 创建nginx配置文件  
目的：
  让后端webserver Listens on port 443 without SSL  
  Forwards requests to your application running on localhost:8000  

注意需要把xxx.compute.amazonaws.com改成实际的ec2 dns名称
```bash 
sudo vim /etc/nginx/sites-available/modelhub
```

```nginx
server {
    listen 80;
    server_name xxx.compute.amazonaws.com;
    location / {
        proxy_pass http://localhost:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}

server {
    listen 443;
    server_name xxx.compute.amazonaws.com;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

- 更改server name bucket size 
- 打开nginx配置文件
```bash
sudo vim /etc/nginx/nginx.conf
```
- 把server_names_hash_bucket_size 改成256
```nginx
http {
    server_names_hash_bucket_size 256;
    # ... other configurations ...
}
```

- 修改llm_modelhub/.env 文件中的域名和端口
```
REACT_APP_API_ENDPOINT==http://xxxx.compute-1.amazonaws.com:443/v1
```

- 生效配置:
```bash
sudo ln -s /etc/nginx/sites-available/modelhub /etc/nginx/sites-enabled/ 
sudo nginx -t 
sudo systemctl restart nginx
```