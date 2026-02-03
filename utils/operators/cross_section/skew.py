description = {
    "description": "计算偏度（截面算子）",
    "args": {
        "x": "输入序列",
        "group_by": "分组字段，默认 'code'"
    },
    "return": "偏度序列",
    "example": "skew(return_ratio, 'date')"
}

def skew(x, group_by='code'):
    """
    偏度算子
    """
    import scipy.stats as stats

    def group_skew(group):
        return stats.skew(group)
    return x.groupby(group_by).transform(group_skew)