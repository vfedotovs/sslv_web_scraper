# Memory Leak Fix - Action Items

## Problem
Uvicorn process memory consumption rises from 245 MB to 1.7 GB over 3 months, causing OOM crashes on 2 GB RAM AWS EC2 instance.

## Root Cause Analysis

### Identified Issues
1. **No worker restart mechanism** - Uvicorn runs indefinitely without worker recycling
2. **Logging handlers accumulation** - Handlers created at module level without cleanup
3. **Data accumulation in imported modules** - Processing modules may retain references to large datasets
4. **No explicit garbage collection** - After processing large datasets, memory isn't actively freed
5. **File system operations** - Directory listings and file checks may accumulate over time

## Proposed Fixes

### 1. Update Dockerfile - Add Worker Restart Configuration
**File**: `src/ws/Dockerfile`

**Change CMD line to:**
```dockerfile
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2", "--max-requests", "100", "--max-requests-jitter", "20", "--timeout-keep-alive", "5"]
```

**Parameters explained:**
- `--workers 2`: Run 2 worker processes (provides redundancy)
- `--max-requests 100`: Restart worker after 100 requests (prevents memory accumulation)
- `--max-requests-jitter 20`: Add randomness (80-120 requests) to prevent all workers restarting simultaneously
- `--timeout-keep-alive 5`: Close keep-alive connections after 5 seconds

### 2. Add Explicit Garbage Collection
**File**: `src/ws/app/main.py`

**Add import:**
```python
import gc
```

**Add garbage collection after each workflow completes:**
```python
# After line 87 (after aws_mailer_main() in first workflow)
gc.collect()

# After line 117 (after aws_mailer_main() in second workflow)
gc.collect()
```

### 3. Add Memory Logging for Monitoring
**File**: `src/ws/app/main.py`

**Add import:**
```python
import psutil
```

**Add function to log memory usage:**
```python
def log_memory_usage():
    """Log current memory usage"""
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    log.info(f"Memory usage: RSS={mem_info.rss / 1024 / 1024:.2f} MB, VMS={mem_info.vms / 1024 / 1024:.2f} MB")
```

**Call at key points:**
- At the start of `run_long_task()`
- After each major operation (scraping, formatting, DB operations)
- After garbage collection

### 4. Update requirements.txt
**File**: `src/ws/requirements.txt`

**Add:**
```
psutil
```

### 5. Add Proper Logging Handler Cleanup
**File**: `src/ws/app/main.py`

**Consider using context manager or shutdown hook:**
```python
import atexit

def cleanup_handlers():
    """Clean up logging handlers on shutdown"""
    for handler in log.handlers[:]:
        handler.close()
        log.removeHandler(handler)

atexit.register(cleanup_handlers)
```

### 6. Review Imported Modules for Memory Leaks
**Files to audit:**
- `app.wsmodules.file_downloader`
- `app.wsmodules.web_scraper`
- `app.wsmodules.data_format_changer`
- `app.wsmodules.df_cleaner`
- `app.wsmodules.db_worker`
- `app.wsmodules.analytics`
- `app.wsmodules.pdf_creator`
- `app.wsmodules.aws_mailer`

**Check for:**
- Global variables that accumulate data
- Unclosed file handles
- Database connections not being closed
- DataFrame operations without explicit deletion
- Large objects not being dereferenced

### 7. Add Health Check Endpoint with Memory Stats
**File**: `src/ws/app/main.py`

```python
@app.get("/health")
def health_check():
    """Health check endpoint with memory stats"""
    process = psutil.Process(os.getpid())
    mem_info = process.memory_info()
    return {
        "status": "healthy",
        "memory_rss_mb": round(mem_info.rss / 1024 / 1024, 2),
        "memory_vms_mb": round(mem_info.vms / 1024 / 1024, 2)
    }
```

## Implementation Priority

### High Priority (Immediate)
1. Update Dockerfile with worker restart parameters
2. Add explicit garbage collection calls
3. Add memory usage logging

### Medium Priority (Next Sprint)
4. Audit all wsmodules for memory leaks
5. Add health check endpoint

### Low Priority (Future)
6. Consider migrating to Gunicorn with timeout settings
7. Implement circuit breaker pattern for external calls
8. Add memory profiling in development environment

## Testing Plan

1. **Before deployment:**
   - Run load tests with memory profiling
   - Monitor memory usage over 1000+ requests

2. **After deployment:**
   - Monitor memory metrics hourly for first 48 hours
   - Set up CloudWatch alarms for memory > 1.5 GB
   - Plan to check memory usage weekly for first month

3. **Success Criteria:**
   - Memory stays below 500 MB after 1 month
   - No OOM crashes
   - Worker restarts happen gracefully every ~100 requests

## Additional Recommendations

1. **Increase EC2 instance size** (short-term mitigation)
   - Move from 2 GB to 4 GB RAM instance
   - Provides breathing room while fixes are implemented

2. **Add Docker memory limits**
   ```dockerfile
   # In docker-compose.yml or ECS task definition
   mem_limit: 1g
   mem_reservation: 512m
   ```

3. **Enable swap** (emergency fallback)
   - Configure swap space on EC2 instance
   - Prevents hard OOM crashes

4. **Set up monitoring alerts**
   - CloudWatch alarm when memory > 1.5 GB
   - Alert on container restarts
   - Track requests/worker lifetime
