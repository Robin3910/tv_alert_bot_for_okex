# coding: utf-8

import sqlite3
import os


class SQliteHelper:

    def __init__(self, filename=""):
        self.filename = filename
        # 创建数据库
        # 连接SQLite数据库
        # 参数:
        #   - filename: 数据库文件名
        #   - isolation_level: 事务隔离级别，None表示不使用事务
        # 返回值: 无
        self.db = sqlite3.connect(self.filename,isolation_level=None)
        self.db.row_factory = sqlite3.Row

        self.c = self.db.cursor()

    def close(self):
        """
        关闭数据库
        """
        self.c.close()
        self.db.close()
    #     开启事务
    def begin(self):
        self.db.execute("BEGIN")
        return True
    # 事务回滚
    def rollback(self):
        self.db.rollback()
        return True
    def commit(self):
        self.db.commit()
        return True
    def execute(self, sql, param=None):
        """
        执行数据库的增、删、改
        sql：sql语句
        param：数据，可以是list或tuple，亦可是None
        retutn：成功返回True
        """
        try:
            if param is None:
                self.c.execute(sql)
            else:
                if type(param) is list:
                    self.c.executemany(sql, param)
                else:
                    self.c.execute(sql, param)
            count = self.db.total_changes
            self.db.commit()
        except Exception as e:
            print(e)
            return False, e
        if count > 0:
            return True
        else:
            return False

    def query(self, sql, param=None):
        """
        查询语句
        sql：sql语句
        param：参数,可为None
        retutn：成功返回True
        """
        if param is None:
            self.c.execute(sql)
        else:
            self.c.execute(sql, param)
        return self.c.fetchall()
    def query_one(self,sql,param=None):
        if param is None:
            self.c.execute(sql)
        else:
            self.c.execute(sql, param)
        return self.c.fetchone()
    # def set(self,table,field=" * ",where="",isWhere=False):
    #     self.table = table
    #     self.filed = field
    #     if where != "" :
    #         self.where = where
    #         self.isWhere = True
    #     return True


if __name__ == "__main__":
    """
    测试代码
    """
    sql = SQliteHelper("test")
    f = sql.execute("create table test (id int not null,name text not null,age int);")
    print("ok")
    sql.execute("insert into test (id,name,age) values (?,?,?);", [(1, 'abc', 15), (2, 'bca', 16)])
    res = sql.query("select * from test;")
    print(res)
    sql.execute("insert into test (id,name) values (?,?);", (3, 'bac'))
    res = sql.query("select * from test where id=?;", (3,))
    print(res)
    sql.close()
