import time
import functools
import threading
from typing import Dict, Any, Optional, Callable
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from collections import defaultdict, deque
from .logging_config import get_performance_logger

logger = get_performance_logger()


@dataclass
class PerformanceMetric:
    name: str
    start_time: float
    end_time: Optional[float] = None
    duration: Optional[float] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def finish(self):
        self.end_time = time.time()
        self.duration = self.end_time - self.start_time
        return self.duration


class PerformanceMonitor:
    
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self.metrics_history = defaultdict(lambda: deque(maxlen=max_history))
        self.active_metrics = {}
        self.lock = threading.Lock()
    
    def start_metric(self, name: str, metadata: Dict[str, Any] = None) -> str:
        metric_id = f"{name}_{int(time.time() * 1000000)}"
        
        metric = PerformanceMetric(
            name=name,
            start_time=time.time(),
            metadata=metadata or {}
        )
        
        with self.lock:
            self.active_metrics[metric_id] = metric
        
        return metric_id
    
    def end_metric(self, metric_id: str) -> Optional[float]:
        with self.lock:
            if metric_id not in self.active_metrics:
                return None
            
            metric = self.active_metrics.pop(metric_id)
            duration = metric.finish()
            
            self.metrics_history[metric.name].append(metric)
            
            logger.info(f"Performance metric completed: {metric.name} took {duration:.4f}s", 
                       extra={
                           'metric_name': metric.name,
                           'duration_seconds': duration,
                           'metadata': metric.metadata
                       })
            
            return duration
    
    def get_statistics(self, metric_name: str) -> Dict[str, Any]:
        with self.lock:
            if metric_name not in self.metrics_history:
                return {}
            
            metrics = list(self.metrics_history[metric_name])
            
            if not metrics:
                return {}
            
            durations = [m.duration for m in metrics if m.duration is not None]
            
            if not durations:
                return {}
            
            return {
                'metric_name': metric_name,
                'count': len(durations),
                'min_duration': min(durations),
                'max_duration': max(durations),
                'avg_duration': sum(durations) / len(durations),
                'total_duration': sum(durations),
                'last_duration': durations[-1],
                'p50': self._percentile(durations, 50),
                'p95': self._percentile(durations, 95),
                'p99': self._percentile(durations, 99)
            }
    
    def get_all_statistics(self) -> Dict[str, Dict[str, Any]]:
        with self.lock:
            return {
                name: self.get_statistics(name)
                for name in self.metrics_history.keys()
            }
    
    def clear_history(self, metric_name: str = None):
        with self.lock:
            if metric_name:
                if metric_name in self.metrics_history:
                    self.metrics_history[metric_name].clear()
            else:
                self.metrics_history.clear()
    
    def _percentile(self, data: list, percentile: float) -> float:
        if not data:
            return 0.0
        
        sorted_data = sorted(data)
        index = (len(sorted_data) - 1) * (percentile / 100.0)
        
        if index.is_integer():
            return sorted_data[int(index)]
        else:
            lower = sorted_data[int(index)]
            upper = sorted_data[int(index) + 1]
            return lower + (upper - lower) * (index - int(index))


performance_monitor = PerformanceMonitor()


def measure_time(metric_name: str = None, include_args: bool = False, log_threshold: float = 0.0):
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            name = metric_name or f"{func.__module__}.{func.__name__}"
            
            metadata = {}
            if include_args:
                metadata['args_count'] = len(args)
                metadata['kwargs_keys'] = list(kwargs.keys())
            
            metric_id = performance_monitor.start_metric(name, metadata)
            
            try:
                result = func(*args, **kwargs)
                return result
            finally:
                duration = performance_monitor.end_metric(metric_id)
                
                if duration and duration > log_threshold:
                    logger.warning(f"Slow operation detected: {name} took {duration:.4f}s")
        
        return wrapper
    return decorator


class PerformanceContext:
    
    def __init__(self, metric_name: str, metadata: Dict[str, Any] = None):
        self.metric_name = metric_name
        self.metadata = metadata or {}
        self.metric_id = None
        self.duration = None
    
    def __enter__(self):
        self.metric_id = performance_monitor.start_metric(self.metric_name, self.metadata)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.metric_id:
            self.duration = performance_monitor.end_metric(self.metric_id)


class ResourceMonitor:
    
    def __init__(self):
        self.start_times = {}
        self.resource_usage = defaultdict(list)
        
    def start_monitoring(self, context: str):
        self.start_times[context] = {
            'timestamp': time.time(),
            'process_time': time.process_time(),
            'thread_time': time.thread_time()
        }
    
    def end_monitoring(self, context: str) -> Dict[str, float]:
        if context not in self.start_times:
            return {}
        
        start_data = self.start_times.pop(context)
        end_time = time.time()
        end_process_time = time.process_time()
        end_thread_time = time.thread_time()
        
        metrics = {
            'wall_time': end_time - start_data['timestamp'],
            'cpu_time': end_process_time - start_data['process_time'],
            'thread_time': end_thread_time - start_data['thread_time']
        }
        
        self.resource_usage[context].append({
            'timestamp': datetime.utcnow().isoformat(),
            'metrics': metrics
        })
        
        return metrics
    
    def get_resource_summary(self, context: str) -> Dict[str, Any]:
        if context not in self.resource_usage:
            return {}
        
        usage_data = self.resource_usage[context]
        
        if not usage_data:
            return {}
        
        wall_times = [data['metrics']['wall_time'] for data in usage_data]
        cpu_times = [data['metrics']['cpu_time'] for data in usage_data]
        
        return {
            'context': context,
            'measurements': len(usage_data),
            'wall_time': {
                'min': min(wall_times),
                'max': max(wall_times),
                'avg': sum(wall_times) / len(wall_times),
                'total': sum(wall_times)
            },
            'cpu_time': {
                'min': min(cpu_times),
                'max': max(cpu_times),
                'avg': sum(cpu_times) / len(cpu_times),
                'total': sum(cpu_times)
            },
            'cpu_efficiency': sum(cpu_times) / sum(wall_times) if sum(wall_times) > 0 else 0
        }


resource_monitor = ResourceMonitor()


class BatchPerformanceTracker:
    
    def __init__(self):
        self.batch_metrics = {}
        self.lock = threading.Lock()
    
    def start_batch(self, batch_id: str, total_items: int):
        with self.lock:
            self.batch_metrics[batch_id] = {
                'start_time': time.time(),
                'total_items': total_items,
                'processed_items': 0,
                'failed_items': 0,
                'processing_times': []
            }
    
    def record_item_processed(self, batch_id: str, processing_time: float, failed: bool = False):
        with self.lock:
            if batch_id not in self.batch_metrics:
                return
            
            metrics = self.batch_metrics[batch_id]
            metrics['processed_items'] += 1
            metrics['processing_times'].append(processing_time)
            
            if failed:
                metrics['failed_items'] += 1
    
    def finish_batch(self, batch_id: str) -> Dict[str, Any]:
        with self.lock:
            if batch_id not in self.batch_metrics:
                return {}
            
            metrics = self.batch_metrics.pop(batch_id)
            end_time = time.time()
            
            total_time = end_time - metrics['start_time']
            processing_times = metrics['processing_times']
            
            result = {
                'batch_id': batch_id,
                'total_time': total_time,
                'total_items': metrics['total_items'],
                'processed_items': metrics['processed_items'],
                'failed_items': metrics['failed_items'],
                'success_rate': (metrics['processed_items'] - metrics['failed_items']) / metrics['processed_items'] if metrics['processed_items'] > 0 else 0,
                'throughput_per_second': metrics['processed_items'] / total_time if total_time > 0 else 0
            }
            
            if processing_times:
                result.update({
                    'avg_item_processing_time': sum(processing_times) / len(processing_times),
                    'min_item_processing_time': min(processing_times),
                    'max_item_processing_time': max(processing_times)
                })
            
            return result


batch_performance_tracker = BatchPerformanceTracker()


def get_system_performance_summary() -> Dict[str, Any]:
    return {
        'performance_metrics': performance_monitor.get_all_statistics(),
        'timestamp': datetime.utcnow().isoformat(),
        'monitor_config': {
            'max_history': performance_monitor.max_history,
            'active_metrics_count': len(performance_monitor.active_metrics)
        }
    }