def format_msg(msg: dict) -> dict:
    # Format the message to be sent to the server
    # The message is a dictionary with the following keys
    _common = msg['common']
    _user = msg['user']

    msg_type = _common['method']
    room_id = _common['roomId']
    user_id = _user['id']
    user_nickname = _user['nickname']
    base_msg = {
        'msg_type': msg_type,
        'room_id': room_id,
        'user':
            {
                'id': user_id, 'nickname': user_nickname, 'short_id': get_value_from_dict(_user, 'shortId'),
                'gender': get_value_from_dict(_user, 'gender'), 'avatars': get_value_from_dict(_user, 'avatarThumb'),
                'badge': get_value_from_dict(_user, 'badgeImageList'),
                'follow_info': get_value_from_dict(_user, 'followInfo'),
                'display_id': get_value_from_dict(_user, 'displayId')
            }
    }

    if msg_type == 'WebcastLikeMessage':
        base_msg.update(extra={
            'count': get_value_from_dict(msg, 'count'),
            'total': get_value_from_dict(msg, 'total')
        })
        pass
    elif msg_type == 'WebcastChatMessage':
        base_msg.update(extra={
            'content': get_value_from_dict(msg, 'content')
        })
        pass
    elif msg_type == 'WebcastMemberMessage':
        base_msg.update(extra={
            'action': get_value_from_dict(msg, 'action'),
            'memberCount': get_value_from_dict(msg, 'memberCount'),
            'anchorDisplayText': get_value_from_dict(msg, 'anchorDisplayText'),
        })
        pass
    elif msg_type == 'WebcastGiftMessage':
        base_msg.update(extra={
            'describe': get_value_from_dict(_common, 'describe'),
            'giftId': get_value_from_dict(msg, 'giftId'),
            'groupCount': get_value_from_dict(msg, 'groupCount'),
            'repeatCount': get_value_from_dict(msg, 'repeatCount'),
            'comboCount': get_value_from_dict(msg, 'comboCount'),
        })
        pass
    return base_msg


def get_value_from_dict(data: dict, key: str):
    # Get the value of the key in the dictionary
    # If the key does not exist, return None
    try:
        return data[key]
    except KeyError:
        return None
