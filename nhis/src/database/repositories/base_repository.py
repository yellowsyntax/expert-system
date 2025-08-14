from abc import ABC, abstractmethod
from typing import TypeVar, Generic, List, Optional, Dict, Any, Union
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, desc, asc, func, text
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
import uuid

T = TypeVar('T')

class BaseRepository(Generic[T], ABC):
    def __init__(self, db_session: Session, model_class: type):
        self.db_session = db_session
        self.model_class = model_class
    
    def create(self, obj_data: Dict[str, Any]) -> T:
        try:
            if 'id' not in obj_data and hasattr(self.model_class, 'id'):
                obj_data['id'] = uuid.uuid4()
            
            if 'created_at' not in obj_data and hasattr(self.model_class, 'created_at'):
                obj_data['created_at'] = datetime.utcnow()
            
            obj = self.model_class(**obj_data)
            self.db_session.add(obj)
            self.db_session.flush()
            self.db_session.refresh(obj)
            return obj
        except SQLAlchemyError as e:
            self.db_session.rollback()
            raise e
    
    def create_many(self, obj_data_list: List[Dict[str, Any]]) -> List[T]:
        try:
            objects = []
            for obj_data in obj_data_list:
                if 'id' not in obj_data and hasattr(self.model_class, 'id'):
                    obj_data['id'] = uuid.uuid4()
                
                if 'created_at' not in obj_data and hasattr(self.model_class, 'created_at'):
                    obj_data['created_at'] = datetime.utcnow()
                
                obj = self.model_class(**obj_data)
                objects.append(obj)
            
            self.db_session.add_all(objects)
            self.db_session.flush()
            return objects
        except SQLAlchemyError as e:
            self.db_session.rollback()
            raise e
    
    def get_by_id(self, obj_id: Union[str, uuid.UUID]) -> Optional[T]:
        if isinstance(obj_id, str):
            obj_id = uuid.UUID(obj_id)
        return self.db_session.query(self.model_class).filter(self.model_class.id == obj_id).first()
    
    def get_all(self, limit: Optional[int] = None, offset: Optional[int] = None) -> List[T]:
        query = self.db_session.query(self.model_class)
        
        if offset:
            query = query.offset(offset)
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def get_by_field(self, field_name: str, value: Any) -> Optional[T]:
        if not hasattr(self.model_class, field_name):
            raise ValueError(f"Field {field_name} does not exist on {self.model_class.__name__}")
        
        field = getattr(self.model_class, field_name)
        return self.db_session.query(self.model_class).filter(field == value).first()
    
    def get_many_by_field(self, field_name: str, value: Any, limit: Optional[int] = None) -> List[T]:
        if not hasattr(self.model_class, field_name):
            raise ValueError(f"Field {field_name} does not exist on {self.model_class.__name__}")
        
        field = getattr(self.model_class, field_name)
        query = self.db_session.query(self.model_class).filter(field == value)
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def get_by_fields(self, filters: Dict[str, Any]) -> Optional[T]:
        query = self.db_session.query(self.model_class)
        
        for field_name, value in filters.items():
            if not hasattr(self.model_class, field_name):
                raise ValueError(f"Field {field_name} does not exist on {self.model_class.__name__}")
            
            field = getattr(self.model_class, field_name)
            if isinstance(value, list):
                query = query.filter(field.in_(value))
            else:
                query = query.filter(field == value)
        
        return query.first()
    
    def get_many_by_fields(self, filters: Dict[str, Any], limit: Optional[int] = None, order_by: Optional[str] = None, desc_order: bool = False) -> List[T]:
        query = self.db_session.query(self.model_class)
        
        for field_name, value in filters.items():
            if not hasattr(self.model_class, field_name):
                raise ValueError(f"Field {field_name} does not exist on {self.model_class.__name__}")
            
            field = getattr(self.model_class, field_name)
            if isinstance(value, list):
                query = query.filter(field.in_(value))
            else:
                query = query.filter(field == value)
        
        if order_by and hasattr(self.model_class, order_by):
            order_field = getattr(self.model_class, order_by)
            if desc_order:
                query = query.order_by(desc(order_field))
            else:
                query = query.order_by(asc(order_field))
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def update(self, obj_id: Union[str, uuid.UUID], update_data: Dict[str, Any]) -> Optional[T]:
        try:
            if isinstance(obj_id, str):
                obj_id = uuid.UUID(obj_id)
            
            if 'updated_at' not in update_data and hasattr(self.model_class, 'updated_at'):
                update_data['updated_at'] = datetime.utcnow()
            
            obj = self.get_by_id(obj_id)
            if obj:
                for key, value in update_data.items():
                    if hasattr(obj, key):
                        setattr(obj, key, value)
                
                self.db_session.flush()
                self.db_session.refresh(obj)
                return obj
            return None
        except SQLAlchemyError as e:
            self.db_session.rollback()
            raise e
    
    def update_by_field(self, field_name: str, field_value: Any, update_data: Dict[str, Any]) -> int:
        try:
            if not hasattr(self.model_class, field_name):
                raise ValueError(f"Field {field_name} does not exist on {self.model_class.__name__}")
            
            if 'updated_at' not in update_data and hasattr(self.model_class, 'updated_at'):
                update_data['updated_at'] = datetime.utcnow()
            
            field = getattr(self.model_class, field_name)
            result = self.db_session.query(self.model_class).filter(field == field_value).update(update_data)
            self.db_session.flush()
            return result
        except SQLAlchemyError as e:
            self.db_session.rollback()
            raise e
    
    def delete(self, obj_id: Union[str, uuid.UUID]) -> bool:
        try:
            if isinstance(obj_id, str):
                obj_id = uuid.UUID(obj_id)
            
            obj = self.get_by_id(obj_id)
            if obj:
                self.db_session.delete(obj)
                self.db_session.flush()
                return True
            return False
        except SQLAlchemyError as e:
            self.db_session.rollback()
            raise e
    
    def delete_by_field(self, field_name: str, value: Any) -> int:
        try:
            if not hasattr(self.model_class, field_name):
                raise ValueError(f"Field {field_name} does not exist on {self.model_class.__name__}")
            
            field = getattr(self.model_class, field_name)
            result = self.db_session.query(self.model_class).filter(field == value).delete()
            self.db_session.flush()
            return result
        except SQLAlchemyError as e:
            self.db_session.rollback()
            raise e
    
    def count(self, filters: Optional[Dict[str, Any]] = None) -> int:
        query = self.db_session.query(func.count(self.model_class.id))
        
        if filters:
            for field_name, value in filters.items():
                if not hasattr(self.model_class, field_name):
                    raise ValueError(f"Field {field_name} does not exist on {self.model_class.__name__}")
                
                field = getattr(self.model_class, field_name)
                if isinstance(value, list):
                    query = query.filter(field.in_(value))
                else:
                    query = query.filter(field == value)
        
        return query.scalar()
    
    def exists(self, filters: Dict[str, Any]) -> bool:
        return self.count(filters) > 0
    
    def execute_raw_query(self, query: str, params: Optional[Dict[str, Any]] = None):
        try:
            if params:
                result = self.db_session.execute(text(query), params)
            else:
                result = self.db_session.execute(text(query))
            return result
        except SQLAlchemyError as e:
            self.db_session.rollback()
            raise e
    
    def get_latest(self, limit: int = 1, order_field: str = 'created_at') -> List[T]:
        if not hasattr(self.model_class, order_field):
            raise ValueError(f"Field {order_field} does not exist on {self.model_class.__name__}")
        
        field = getattr(self.model_class, order_field)
        return self.db_session.query(self.model_class).order_by(desc(field)).limit(limit).all()
    
    def get_date_range(self, date_field: str, start_date: datetime, end_date: datetime, limit: Optional[int] = None) -> List[T]:
        if not hasattr(self.model_class, date_field):
            raise ValueError(f"Field {date_field} does not exist on {self.model_class.__name__}")
        
        field = getattr(self.model_class, date_field)
        query = self.db_session.query(self.model_class).filter(
            and_(field >= start_date, field <= end_date)
        )
        
        if limit:
            query = query.limit(limit)
            
        return query.all()
    
    def commit(self):
        try:
            self.db_session.commit()
        except SQLAlchemyError as e:
            self.db_session.rollback()
            raise e
    
    def rollback(self):
        self.db_session.rollback()
    
    def close(self):
        self.db_session.close()