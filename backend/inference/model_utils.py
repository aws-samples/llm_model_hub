from typing import Annotated, Sequence, TypedDict, Dict, Optional,List, Any,TypedDict
from utils.config import DEFAULT_REGION
from types import MethodType
from transformers import PreTrainedModel, PreTrainedTokenizerBase,AutoProcessor,AutoConfig
from utils.llamafactory.hparams.model_args import ModelArguments
if DEFAULT_REGION.startswith('cn'):
    from modelscope import  AutoTokenizer
else:
    from transformers import  AutoTokenizer,AutoProcessor,AutoConfig

from logger_config import setup_logger
import logging
logger = setup_logger('model_utils.py', level=logging.INFO)

def _get_init_kwargs(model_args) -> Dict[str, Any]:
    r"""
    Gets arguments to load config/tokenizer/model.

    Note: including inplace operation of model_args.
    """
    return {
        "trust_remote_code": True,
        "cache_dir": model_args['cache_dir'],
        "revision": model_args['revision'],
        "token": model_args['token'],
        "model_name_or_path":model_args['model_name_or_path'],
        # "new_special_tokens": model_args.get('new_special_tokens'),
        # "cache_dir": model_args.cache_dir,
        # "revision": model_args.model_revision,
        # "token": model_args.hf_hub_token,
    }

#https://github.com/hiyouga/LLaMA-Factory/blob/e22ac05fd7a581a0615ef03f514a54f7d7674594/src/llamafactory/model/model_utils/visual.py
def get_image_seqlen(config: "PretrainedConfig") -> int:
    r"""
    Computes the number of special tokens per image.
    """
    model_type = getattr(config, "model_type", None)
    if model_type == "llava":
        image_seqlen = (config.vision_config.image_size // config.vision_config.patch_size) ** 2
        if getattr(config, "vision_feature_select_strategy", "default") == "full":  # add [CLS] token
            image_seqlen += 1
    elif model_type == "paligemma":
        image_seqlen = config.vision_config.num_image_tokens
    elif model_type == "qwen2_vl":  # variable length
        image_seqlen = -1
    return image_seqlen

def load_config(model_args) -> "PretrainedConfig":
    r"""
    Loads model config.
    """
    init_kwargs = _get_init_kwargs(model_args)
    return AutoConfig.from_pretrained(model_args['model_name_or_path'], **init_kwargs)

def patch_tokenizer(tokenizer: "PreTrainedTokenizer") -> None:
    if "PreTrainedTokenizerBase" not in str(tokenizer._pad.__func__):
        tokenizer._pad = MethodType(PreTrainedTokenizerBase._pad, tokenizer)


def load_tokenizer_ms(model_args):
    """
    Loads pretrained tokenizer.

    Note: including inplace operation of model_args.
    """
    init_kwargs = _get_init_kwargs(model_args)
    logger.info(f'init_kwargs:{model_args}')
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            model_args['model_name_or_path'],
            use_fast=False,
            # split_special_tokens=model_args.split_special_tokens,
            padding_side="right",
            **init_kwargs,
        )
    except ValueError:  # try the fast one
        tokenizer = AutoTokenizer.from_pretrained(
            model_args['model_name_or_path'],
            use_fast=True,
            padding_side="right",
            **init_kwargs,
        )
    except Exception:
        logger.warning("Fail to load tokenizer from huggingface")
        tokenizer = None
    return tokenizer


def load_tokenizer_hf(model_args):
    r"""
    Loads pretrained tokenizer.

    Note: including inplace operation of model_args.
    """
    init_kwargs = _get_init_kwargs(model_args)

    logger.info(f'init_kwargs:{model_args}')
    try:
        tokenizer = AutoTokenizer.from_pretrained(
            model_args['model_name_or_path'],
            use_fast=False,
            # split_special_tokens=model_args.split_special_tokens,
            padding_side="right",
            **init_kwargs,
        )
    except ValueError:  # try the fast one
        tokenizer = AutoTokenizer.from_pretrained(
            model_args['model_name_or_path'],
            use_fast=True,
            padding_side="right",
            **init_kwargs,
        )
    except Exception:
        logger.warning("Fail to load tokenizer from huggingface")
        tokenizer = None

    if tokenizer:
        if model_args.get('new_special_tokens') is not None:
            num_added_tokens = tokenizer.add_special_tokens(
                dict(additional_special_tokens=model_args.new_special_tokens),
                replace_additional_special_tokens=False,
            )
            logger.info("Add {} to special tokens.".format(",".join(model_args.new_special_tokens)))
            if num_added_tokens > 0 and not model_args.resize_vocab:
                model_args.resize_vocab = True
                logger.warning("New tokens have been added, changed `resize_vocab` to True.")

        patch_tokenizer(tokenizer)
    else:
        try:
            processor = AutoProcessor.from_pretrained(model_args['model_name_or_path'], **init_kwargs)
        except Exception:
            processor = None
        print("--processor:")
        print(processor)

        # Avoid load tokenizer, see:
        # https://github.com/huggingface/transformers/blob/v4.40.0/src/transformers/models/auto/processing_auto.py#L324
        if "Processor" not in processor.__class__.__name__:
            processor = None

        if  processor and tokenizer is None:
            logger.info("load tokenizer from processor.")
            tokenizer = processor.tokenizer

    return tokenizer



def load_tokenizer(model_args):
    if DEFAULT_REGION.startswith('cn'):
        return load_tokenizer_ms(model_args)
    else:
        return load_tokenizer_hf(model_args)

def apply_default_chat_template(conversation, tokenize=True, add_generation_prompt=False):
    """
    Applies a chat template to a conversation.

    Args:
        conversation (List[Dict]): A list of dictionaries representing the conversation.
            Each dictionary should have 'role' and 'content' keys.
        tokenize (bool, optional): Whether to tokenize the result. Defaults to True.
        add_generation_prompt (bool, optional): Whether to add a generation prompt at the end. Defaults to False.

    Returns:
        Union[str, List[int]]: The formatted conversation as a string or list of token ids.
    """
    result = ""
    for message in conversation:
        role = message['role']
        content = message['content']
        
        if role == 'system':
            result += f"{content}\n\n"
        elif role == 'user':
            result += f"{content}\n\n"
        elif role == 'assistant':
            result += f"{content}\n\n"
        else:
            raise ValueError(f"Unknown role: {role}")
    return result