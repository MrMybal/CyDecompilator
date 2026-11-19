"""Stable application error envelope retained for existing scripts and projects."""
class CyToolError(Exception):
    def __init__(self, code, message, *, recoverable=False, details=None, **extra):
        super().__init__(message)
        self.code, self.message = code, str(message)
        self.recoverable, self.details = bool(recoverable), details
    def to_dict(self):
        value={'code':self.code,'message':self.message,'recoverable':self.recoverable}
        if self.details is not None: value['details']=self.details
        return value
AppError=CyToolError
