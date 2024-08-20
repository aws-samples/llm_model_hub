## ENV Setup

### Install python virtual env
```bash
conda create -n py311 python=3.11
conda activate py311
```

### Install requirements
```bash
pip install -r requirements.txt
```

### Setup MYSQL
- Install Docker
Log in to the EC2 instance using SSH command as the ec2-user user or use the AWS EC2 Instance Connect feature in the EC2 console to log in to the command line. 

In the session, execute the following commands.
 **Note: Execute each command one line at a time.**
```bash  
# Install components
sudo yum install docker python3-pip git -y && pip3 install -U awscli && pip install pyyaml==5.3.1 && pip3 install docker-compose


# Fix docker python wrapper 7.0 SSL version issue  
pip3 install docker==6.1.3

# Configure components
sudo systemctl enable docker && sudo systemctl start docker && sudo usermod -aG docker $USER

```

- Pull the MySQL Docker image:
Open a terminal and run the following command to download the official MySQL image:
- Create and run a MySQL container:
```bash
docker run -d \
  --name hub-mysql \
  -p 3306:3306 \
  -e MYSQL_ROOT_PASSWORD=1234560 \
  -e MYSQL_DATABASE=llm \
  -e MYSQL_USER=llmdata \
  -e MYSQL_PASSWORD=llmdata \
  -v mysql-data:/var/lib/mysql \
  -v $(pwd)/scripts:/opt/data \
  --restart always \
  mysql:8.0
```

- Verify the container is running:
```bash
docker ps
```

- Download script file and setup the database:
```bash
cd scripts 

docker exec hub-mysql sh -c "mysql -u root -p1234560 -D llm  < /opt/data/mysql_setup.sql"
```

- To login in cmd line
```bash
docker exec -it hub-mysql mysql -u root -p1234560
```

- To stop the container when you're done, use:
```bash
docker stop hub-mysql
```

- To remove the container when you're done, use:
```bash
docker rm hub-mysql
```

- To start it again later, use:
```bash
docker start hub-mysql
```

### Run
```bash
python3 server.py --host 0.0.0.0 --port 8000
```

