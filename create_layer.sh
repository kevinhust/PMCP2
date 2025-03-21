#!/bin/bash

# 创建临时目录
echo "Creating temporary directory..."
mkdir -p layer/python

# 安装依赖到layer目录
echo "Installing dependencies..."
pip install numpy -t layer/python/
pip install TA-Lib -t layer/python/

# 创建zip文件
echo "Creating layer zip file..."
cd layer
zip -r ../ta_lib_layer.zip python/

# 清理临时文件
echo "Cleaning up..."
cd ..
rm -rf layer

echo "Layer packaging completed! Layer file is in ta_lib_layer.zip" 