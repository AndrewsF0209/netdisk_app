from flask import Flask, request, jsonify, send_from_directory, send_file, escape
from flask_cors import CORS
import os
import shutil
from datetime import datetime

app = Flask(__name__, static_folder='static', static_url_path='')
CORS(app)

# 配置根存储路径（请确保debian用户有读写权限）
ROOT_FOLDER = '/home/debian/netdisk_storage'
os.makedirs(ROOT_FOLDER, exist_ok=True)

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB


# 根路径指向前端
@app.route('/')
def serve_frontend():
    return send_file('static/index.html')


# 安全校验：防止路径穿越（非常重要！）
def safe_join(base, path):
    # 清理路径，防止 ../../ 这种恶意访问
    safe_path = os.path.abspath(os.path.join(base, path))
    # 确保拼接后的路径仍在根目录内
    if os.path.commonprefix([safe_path, os.path.abspath(base)]) != os.path.abspath(base):
        return None
    return safe_path


# 1. 获取文件/文件夹列表（支持路径）
@app.route('/api/list', methods=['GET'])
def list_files():
    try:
        # 获取当前路径参数，默认为空（根目录）
        current_path = request.args.get('path', '')
        target_path = safe_join(ROOT_FOLDER, current_path)

        if target_path is None or not os.path.exists(target_path):
            return jsonify({'code': -1, 'msg': '路径不存在或无权限'})

        items = []
        # 遍历目录，区分文件和文件夹
        for name in os.listdir(target_path):
            item_path = os.path.join(target_path, name)
            stats = os.stat(item_path)

            if os.path.isdir(item_path):
                items.append({
                    'name': name,
                    'type': 'dir',
                    'modify_time': datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'path': os.path.relpath(item_path, ROOT_FOLDER)
                })
            else:
                items.append({
                    'name': name,
                    'type': 'file',
                    'size': stats.st_size,
                    'modify_time': datetime.fromtimestamp(stats.st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                    'path': os.path.relpath(item_path, ROOT_FOLDER)
                })

        # 排序：文件夹在前，文件在后，按名称排序
        items.sort(key=lambda x: (x['type'] != 'dir', x['name'].lower()))

        return jsonify({
            'code': 0,
            'data': {
                'items': items,
                'current_path': current_path  # 返回当前路径，用于前端导航
            },
            'msg': '获取成功'
        })
    except Exception as e:
        return jsonify({'code': -1, 'msg': f'获取失败：{str(e)}'})


# 2. 上传文件（支持指定目录）
@app.route('/api/upload', methods=['POST'])
def upload_file():
    try:
        current_path = request.form.get('path', '')
        target_folder = safe_join(ROOT_FOLDER, current_path)

        if target_folder is None or not os.path.exists(target_folder):
            return jsonify({'code': -1, 'msg': '上传路径无效'})

        if 'file' not in request.files:
            return jsonify({'code': -1, 'msg': '未选择文件'})

        file = request.files['file']
        if file.filename == '':
            return jsonify({'code': -1, 'msg': '文件名不能为空'})

        file_path = os.path.join(target_folder, file.filename)
        file.save(file_path)

        return jsonify({'code': 0, 'msg': '上传成功'})
    except Exception as e:
        return jsonify({'code': -1, 'msg': f'上传失败：{str(e)}'})


# 3. 下载文件
@app.route('/api/download', methods=['GET'])
def download_file():
    try:
        file_path = request.args.get('path')
        safe_path = safe_join(ROOT_FOLDER, file_path)

        if safe_path is None or not os.path.isfile(safe_path):
            return jsonify({'code': -1, 'msg': '文件不存在'})

        # 分离目录和文件名，使用send_from_directory
        directory = os.path.dirname(safe_path)
        filename = os.path.basename(safe_path)
        return send_from_directory(directory, filename, as_attachment=True)
    except Exception as e:
        return jsonify({'code': -1, 'msg': f'下载失败：{str(e)}'})


# 4. 创建文件夹
@app.route('/api/mkdir', methods=['POST'])
def make_dir():
    try:
        current_path = request.json.get('path', '')
        dir_name = request.json.get('name', '')

        if not dir_name:
            return jsonify({'code': -1, 'msg': '文件夹名不能为空'})

        target_path = safe_join(ROOT_FOLDER, os.path.join(current_path, dir_name))

        if target_path is None:
            return jsonify({'code': -1, 'msg': '路径非法'})

        if os.path.exists(target_path):
            return jsonify({'code': -1, 'msg': '文件夹已存在'})

        os.makedirs(target_path)
        return jsonify({'code': 0, 'msg': '创建成功'})
    except Exception as e:
        return jsonify({'code': -1, 'msg': f'创建失败：{str(e)}'})


# 5. 删除文件或文件夹
@app.route('/api/delete', methods=['POST'])
def delete_item():
    try:
        item_path = request.json.get('path')
        safe_path = safe_join(ROOT_FOLDER, item_path)

        if safe_path is None or not os.path.exists(safe_path):
            return jsonify({'code': -1, 'msg': '目标不存在'})

        if os.path.isdir(safe_path):
            # 删除文件夹（包括非空文件夹）
            shutil.rmtree(safe_path)
        else:
            # 删除文件
            os.remove(safe_path)

        return jsonify({'code': 0, 'msg': '删除成功'})
    except Exception as e:
        return jsonify({'code': -1, 'msg': f'删除失败：{str(e)}'})

# 6. 获取存储容量信息（修复 exFAT 挂载点问题）
@app.route('/api/storage', methods=['GET'])
def get_storage_info():
    try:
        # 使用 shutil.disk_usage 读取挂载点容量，兼容 exFAT
        usage = shutil.disk_usage(ROOT_FOLDER)

        total = usage.total
        used = usage.used
        free = usage.free
        percentage = round((used / total) * 100, 2) if total > 0 else 0

        return jsonify({
            'code': 0,
            'data': {
                'total': total,
                'used': used,
                'free': free,
                'percentage': percentage
            },
            'msg': '获取成功'
        })
    except Exception as e:
        return jsonify({'code': -1, 'msg': f'获取存储信息失败：{str(e)}'})


# 处理图标请求
@app.route('/favicon.ico')
def favicon():
    return '', 204


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080, debug=False)  # 生产环境关闭debug
