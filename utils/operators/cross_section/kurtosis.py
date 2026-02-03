description = {
    "description": "计算峰度（截面算子）",
    "args": {
        "x": "输入序列",
        "group_by": "分组字段，默认'code'"
    },
    "return": "峰度序列",
    "example": "kurtosis(return_ratio, 'date')"
}

def kurtosis(x, group_by='code'):
    """
    峰度算子
    """
    import scipy.stats as stats
    
    def group_kurtosis(group):
        return stats.kurtosis(group)
    return x.groupby(group_by).transform(group_kurtosis)