import logging

import flask
from live import Live
from flask import request

Worker = {}

app = flask.Flask(__name__)


@app.route('/api/v1/worker', methods=['POST'])
def create_worker():
    global Worker
    data = request.get_json()
    if data is None:
        return flask.jsonify({'code': 400, 'msg': 'Bad Request'}), 400

    live_url = data.get('live_url')
    socket_addr = data.get('socket_addr')

    if live_url in Worker:
        return flask.jsonify({'code': 0, 'msg': 'worker already exists'})
    else:
        try:
            live = Live(live_url, callback_socket=socket_addr)
            Worker[live.id] = live
            live.start()
            return flask.jsonify({'code': 0, 'msg': 'create worker success', 'data': {'id': live.id}})
        except Exception as e:
            print('create worker for ' + live_url + ' failed: ', e)
            return flask.jsonify({'code': 500, 'msg': 'create worker failed'}), 500


@app.route('/api/v1/worker', methods=['DELETE'])
def delete_worker():
    global Worker

    work_id = request.args.get('id')

    if work_id in Worker:
        live = Worker[work_id]
        try:
            live.stop()
        except Exception as e:
            print('stop worker for ' + live.id + ' failed: ', e)
        del Worker[work_id]
        return flask.jsonify({'code': 0, 'msg': 'delete worker success'})

    return flask.jsonify({'code': 404, 'msg': 'worker not found'}), 404


@app.route('/api/v1/worker', methods=['GET'])
def get_worker():
    global Worker

    work_id = request.args.get('id')

    if work_id in Worker:
        live = Worker[work_id]
        return flask.jsonify({'code': 0, 'msg': 'get worker success', 'data': live.info})

    return flask.jsonify({'code': 404, 'msg': 'worker not found'}), 404


if __name__ == '__main__':
    LOG_FORMAT = "%(asctime)s - %(levelname)s - %(message)s"
    logging.basicConfig(level=logging.DEBUG, format=LOG_FORMAT)
    app.run(host='0.0.0.0', port=8080, debug=True)

