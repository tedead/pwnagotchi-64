import os
import time
import logging

# https://stackoverflow.com/questions/40426502/is-there-a-way-to-suppress-the-messages-tensorflow-prints/40426709
# os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'  # or any {'0', '1', '2'}


def load(config, agent, epoch, from_disk=True):
    config = config['ai']
    if not config['enabled']:
        logging.info("ai disabled")
        return False

    try:
        begin = time.time()

        logging.info("[AI] bootstrapping dependencies ...")

        start = time.time()
        from stable_baselines3 import A2C
        logging.debug("[AI] A2C imported in %.2fs" % (time.time() - start))

        start = time.time()
        from stable_baselines3.a2c import MlpPolicy
        logging.debug("[AI] MlpPolicy imported in %.2fs" % (time.time() - start))

        start = time.time()
        from stable_baselines3.common.vec_env import DummyVecEnv
        logging.debug("[AI] DummyVecEnv imported in %.2fs" % (time.time() - start))

        start = time.time()
        import pwnagotchi.ai.gym as wrappers
        logging.debug("[AI] gym wrapper imported in %.2fs" % (time.time() - start))
    except ImportError as e:
        logging.error("[AI] missing dependency (%s), install with: pip install 'pwnagotchi[ai]'", e)
        return False

    try:
        env = wrappers.Environment(agent, epoch)
        env = DummyVecEnv([lambda: env])

        logging.info("[AI] creating model ...")

        start = time.time()
        a2c = A2C(MlpPolicy, env, **config['params'])
        logging.debug("[AI] A2C created in %.2fs" % (time.time() - start))

        if from_disk and os.path.exists(config['path']):
            logging.info("[AI] loading %s ..." % config['path'])
            start = time.time()
            try:
                a2c = A2C.load(config['path'], env=env)
                logging.debug("[AI] A2C loaded in %.2fs" % (time.time() - start))
            except Exception as e:
                # an incompatible or corrupt brain (e.g. different channel set) must not stop the unit
                logging.exception("[AI] could not load %s (%s), starting with a fresh brain", config['path'], e)
                os.replace(config['path'], "%s.bad" % config['path'])
        else:
            logging.info("[AI] model created:")
            for key, value in config['params'].items():
                logging.info("      %s: %s" % (key, value))

        logging.debug("[AI] total loading time is %.2fs" % (time.time() - begin))

        return a2c
    except Exception as e:
        logging.exception("[AI] error while starting AI (%s)", e)

    logging.warning("[AI] AI not loaded!")
    return False
