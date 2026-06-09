import pandas as pd
import dolphindb as ddb
import threading
from .config import DB_CONFIG
_db_locks = {}
def _get_lock(db: str) -> threading.Lock:
    """获取指定市场的锁（每个市场独立）"""
    if db not in _db_locks:
        _db_locks[db] = threading.Lock()
    return _db_locks[db]

def _connect_dolphindb(db: str) -> ddb.session:
    db_config = DB_CONFIG[db]
    con = ddb.session()
    ok = con.connect(
        db_config["host"],
        int(db_config["port"]),
        db_config["user"],
        db_config["password"],
    )
    if not ok:
        raise RuntimeError("Failed to connect DolphinDB")
    return con

def _dolphindb_type(dtype: pd.api.extensions.ExtensionDtype) -> str:
    dtype_str = str(dtype)
    if "datetime" in dtype_str:
        return "NANOTIMESTAMP"
    if "int" in dtype_str:
        return "LONG"
    if "float" in dtype_str:
        return "DOUBLE"
    if "bool" in dtype_str:
        return "BOOL"
    return "STRING"


def save_dataframe(df: pd.DataFrame, table: str, db: str, freq: str = "day", primary_key: list = None):
    """
    将 DataFrame 写入指定市场的指定表。
    数据库与表不存在时按 freq 对应模板初始化后写入。
    """
    if df is None or df.empty:
        return

    db_path = f"dfs://{db}_{freq}"
    metadata_db_path = f"dfs://{db}_metadata"
    try:
        cols = df.columns.astype(str).tolist()
        if not cols:
            return
        col_defs = ", ".join([f"`{c}" for c in cols])
        compress_methods = ", ".join(["`delta" if c == "date" else "`lz4" for c in cols])
        compress_expr = f"dict([{col_defs}], [{compress_methods}])"
        types = ", ".join([_dolphindb_type(df[c].dtype) for c in cols])
        sort_clause = ""
        if primary_key:
            sort_clause = f", sortColumns=[{', '.join([f'`{c}' for c in primary_key])}]"
        lock = _get_lock(db)
        with lock:
            s = _connect_dolphindb(db)
            if not bool(s.run(f'existsDatabase("{metadata_db_path}")')):
                s.run(f'database("{metadata_db_path}", VALUE, [`meta], , "OLAP")')
            if not bool(s.run(f'existsTable("{metadata_db_path}",`freq)')):
                s.run(
                    f'''
                    mdb=database("{metadata_db_path}");
                    mt=table(1:0, [`table, `freq], [STRING, STRING]);
                    mdb.createTable(mt, `freq);
                    '''
                )
            existing = s.run(
                f'''
                select freq from loadTable("{metadata_db_path}",`freq)
                where table="{table}"
                '''
            )
            if len(existing) > 0:
                existing_freq = str(existing.iloc[0]["freq"])
                if existing_freq != freq:
                    raise ValueError(
                        f"Table '{table}' already registered with freq '{existing_freq}', got '{freq}'."
                    )
            else:
                s.run(
                    f'''
                    ft=loadTable("{metadata_db_path}",`freq);
                    row=table("{table}" as table, "{freq}" as freq);
                    append!(ft, row);
                    '''
                )
            if not bool(s.run(f'existsDatabase("{db_path}")')):
                if freq == "tick":
                    s.run(
                        f'''
                        db1=database("", VALUE, 2000.06.09..2035.06.09);
                        db2=database("", HASH, [SYMBOL, 25]);
                        database("{db_path}", COMPO, [db1, db2], engine="TSDB");
                        '''
                    )
                elif freq == "minute":
                    s.run(f'database("{db_path}", VALUE, 2000.06.09..2035.06.09, engine="TSDB")')
                elif freq == "day":
                    s.run(f'database("{db_path}", RANGE, 1970.01M + (0..66) * 12, engine="TSDB")')
                else:
                    raise ValueError(f"Unsupported freq: {freq}")
            if not bool(s.run(f'existsTable("{db_path}",`{table})')):
                if freq == "tick":
                    create_sql = f'''
                    db=database("{db_path}");
                    schema_t=table(1:0, [{col_defs}], [{types}]);
                    db.createPartitionedTable(schema_t, `{table}, `date`symbol, compressMethods={compress_expr}{sort_clause}, keepDuplicates=LAST, softDelete=true);
                    '''
                    # db.createPartitionedTable(schema_t, `{table}, `date`symbol, compressMethods={compress_expr}{sort_clause}, keepDuplicates=LAST, softDelete=true);
                elif freq == "minute":
                    create_sql = f'''
                    db=database("{db_path}");
                    schema_t=table(1:0, [{col_defs}], [{types}]);
                    db.createPartitionedTable(schema_t, `{table}, `date, compressMethods={compress_expr}{sort_clause}, keepDuplicates=LAST, softDelete=true);
                    '''
                elif freq == "day":
                    create_sql = f'''
                    db=database("{db_path}");
                    schema_t=table(1:0, [{col_defs}], [{types}]);
                    db.createPartitionedTable(schema_t, `{table}, `date, compressMethods={compress_expr}{sort_clause}, keepDuplicates=LAST, softDelete=true);
                    '''
                else:
                    raise ValueError(f"Unsupported freq: {freq}")
                s.run(create_sql)
            var_name = f"up_{table}"
            s.upload({var_name: df})
            if primary_key:
                pk_expr = "".join([f"`{c}" for c in primary_key])
                s.run(
                    f'''
                    t=loadTable("{db_path}",`{table});
                    upsert!(t,{var_name},false,{pk_expr});
                    '''
                )
            else:
                s.run(
                    f'''
                    t=loadTable("{db_path}",`{table});
                    t.append!({var_name});
                    '''
                )
    except:
        return


def load_dataframe(sql: str, db: str):
    """
    直接执行 DolphinDB 语句并返回 DataFrame。
    调用方需传入符合 DolphinDB 语法的查询语句和对应数据库配置名。
    """
    if not sql:
        return pd.DataFrame()
    try:
        s = _connect_dolphindb(db)
        return s.run(sql)
    except:
        return pd.DataFrame()


def loadTable(field, table: str, db: str, cond: str = "") -> str:
    if isinstance(field, str):
        field_expr = field
    else:
        field_expr = ", ".join(field)
    metadata = f"dfs://{db}_metadata"
    try:
        freq_df = load_dataframe(
            f'''
            select freq from loadTable("{metadata}",`freq)
            where table="{table}"
            ''',
            db,
        )
        if freq_df.empty:
            return None
    except:
        return None
    freq = str(freq_df.iloc[0]["freq"])
    db_name = f"dfs://{db}_{freq}"
    return f"select {field_expr} from loadTable('{db_name}','{table}') {cond}"


def dropTable(db: str, table: str) -> bool:
    """删除 DolphinDB 分布式表，不存在时返回 False。"""
    metadata = f"dfs://{db}_metadata"
    try:
        freq_df = load_dataframe(
            f'''
            select freq from loadTable("{metadata}",`freq)
            where table="{table}"
            ''',
            db,
        )
        if freq_df.empty:
            return False
        freq = str(freq_df.iloc[0]["freq"])
        db_path = f"dfs://{db}_{freq}"

        if not bool(load_dataframe(f'existsTable("{db_path}",`{table})', db)):
            return False
        s = _connect_dolphindb(db)
        s.dropTable(f"{db_path}",f"{table}")
        return True
    except:
        return False
