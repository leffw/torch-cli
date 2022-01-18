#!/bin/bash

if ! which docker > /dev/null; then
    echo 'Docker is not installed.'
    exit 1
fi

if ! which docker-compose > /dev/null; then
    echo 'Docker-compose is not installed.'
    exit 1
fi

path=$(echo ~/.torch)

chmod +x *
mkdir -p $path/data

cp -f -r ./data $path
cp -f -r ./docker-compose.yaml $path
cp -f -r ./config.json $path

pip3 install -r requirements.txt
sudo cp ./torch-cli.py /usr/bin/torch-cli
