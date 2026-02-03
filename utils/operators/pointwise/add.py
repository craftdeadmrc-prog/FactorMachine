description = {
    "description": "点态加法算子，逐元素计算 x + y",
    "args": {
        "x": "左操作数，可以是标量、序列或数组",
        "y": "右操作数，可以是标量、序列或数组"
    },
    "return": "逐元素相加后的结果，类型与输入广播后的类型一致",
    "example": "add(close, open)"
}

def add(x, y):
    """
    点态加法算子
    """
    return x + y