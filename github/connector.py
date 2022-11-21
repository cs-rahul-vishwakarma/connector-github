from connectors.core.connector import Connector
from connectors.core.connector import get_logger, ConnectorError
from .operations import _check_health, operations

logger = get_logger('github')


class GitHub(Connector):
    def execute(self, config, operation, params, *args, **kwargs):
        try:
            logger.info('In execute() Operation: {}'.format(operation))
            operation = operations.get(operation)
            return operation(config, params)
        except Exception as err:
            logger.error('An exception occurred {}'.format(err))
            raise ConnectorError('{}'.format(err))

    def check_health(self, config):
        try:
            return _check_health(config)
        except Exception as e:
            logger.exception("An exception occurred {}".format(e))
            raise ConnectorError(e)
