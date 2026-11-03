bind = "127.0.0.1:8000"
workers = 2
accesslog = None
errorlog = "-"
# Gunicorn 25 otherwise creates a control socket in the user's home directory.
control_socket_disable = True
