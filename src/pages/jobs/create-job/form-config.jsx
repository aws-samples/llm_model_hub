// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0
export const SSL_CERTIFICATE_OPTIONS = [
  {
    label: 'Default CloudFront SSL/TLS certificate',
    value: 'default',
    description: 'Provides HTTPS or HTTP access to your content using a CloudFront domain name.',
  },
  {
    label: 'Custom SSL/TLS certificate (example.com)',
    value: 'custom',
    description: 'Grants access by using an alternate domain name, such as https://www.example.com/.',
  },
];

export const FT_OPTIONS = [
  { label: 'Lora', value: 'lora' },
  { label: 'Full', value: 'full' },
]

export const TRAINING_PRECISION = [
  { label: 'bf16', value: 'bf16' },
  { label: 'fp16', value: 'fp16' },
  { label: 'fp32', value: 'fp32' },
  { label: 'pure_bf16', value: 'pure_bf16' },
]

export const BOOSTER_OPTIONS = [
  { label: 'None', value: 'auto' },
  { label: 'FlashAttn2', value: 'fa2' },
  { label: 'unsloth', value: 'use_unsloth' },
  { label:'liger_kernel',value:'liger_kernel'}
]

export const  INSTANCE_TYPES =[
  { label: 'ml.g4dn.2xlarge', value: 'ml.g4dn.2xlarge' },
  { label: 'ml.g4dn.12xlarge', value: 'ml.g4dn.12xlarge' },
  { label: 'ml.g5.2xlarge', value: 'ml.g5.2xlarge' },
  { label: 'ml.g5.12xlarge', value: 'ml.g5.12xlarge' },
  { label: 'ml.g5.48xlarge', value: 'ml.g5.48xlarge' },
  { label: 'ml.g6.2xlarge', value: 'ml.g6.2xlarge' },
  { label: 'ml.g6.12xlarge', value: 'ml.g6.12xlarge' },
  { label: 'ml.g6.48xlarge', value: 'ml.g6.48xlarge' },
  { label: 'ml.g6e.2xlarge', value: 'ml.g6e.2xlarge' },
  { label: 'ml.g6e.12xlarge', value: 'ml.g6e.12xlarge' },
  { label: 'ml.g6e.48xlarge', value: 'ml.g6e.48xlarge' },
  { label: 'ml.p4d.24xlarge', value: 'ml.p4d.24xlarge' },
  { label: 'ml.p4de.24xlarge', value: 'ml.p4de.24xlarge' },
  { label: 'ml.p5.48xlarge', value: 'ml.p5.48xlarge' },
  { label: 'ml.p5e.48xlarge', value: 'ml.p5e.48xlarge' },
  { label: 'ml.p5en.48xlarge', value: 'ml.p5en.48xlarge' }
]


export const TRAINING_STAGES = [
  { label: 'Supervised Fine-Tuning', value: 'sft' },
  { label: 'Pre-Training', value: 'pt' },
  // { label: 'Reward Modeling', value: 'rm' },
  { label: 'DPO', value: 'dpo' },
  { label: 'KTO', value: 'kto' },
  { label: 'GRPO', value: 'grpo' },
  { label: 'DAPO', value: 'dapo' },

]
export const OPTMIZERS =[
  { label: 'adamw_torch', value: 'adamw_torch' },
  { label: 'adamw_8bit', value: 'adamw_8bit' },
  { label: 'adafactor', value: 'adafactor' },
]

export const DEEPSPEED =[
  { label: 'None', value: 'none' },
  // { label: 'Stage 1', value: 'stage_1' ,description:'Only optimizer states is partitioned'},
  { label: 'Stage 2', value: 'stage_2', description:'optimizer states + gradients are partitioned' },
  { label: 'Stage 3', value: 'stage_3' ,description:'Stage 2 + weights are partitioned'  }
]

export const QUANT_OPTIONS = [
  { label: 'None', value: 'none' },
  { label: '8', value: '8' },
  { label: '4', value: '4' },
]
export const SUPPORTED_HTTP_VERSIONS_OPTIONS = [
  { label: 'HTTP 2', value: 'http2' },
  { label: 'HTTP 1', value: 'http1' },
];

export const VIEWER_PROTOCOL_POLICY_OPTIONS = [
  { label: 'HTTP and HTTPS', value: '0' },
  { label: 'Redirect HTTP to HTTPS', value: '1' },
  { label: 'HTTPS only', value: '2' },
];

export const ALLOWED_HTTP_METHOD_OPTIONS = [
  { label: 'GET, HEAD', value: '0' },
  { label: 'GET, HEAD, OPTIONS', value: '1' },
  { label: 'GET, HEAD, OPTIONS, PUT, POST, PATCH', value: '2' },
];

export const FORWARD_HEADER_OPTIONS = [
  { label: 'None', value: 'none' },
  { label: 'Allow list', value: 'allowlist' },
  { label: 'All', value: 'all' },
];

export const COOKIE_OPTIONS = [
  { label: 'None', value: 'none' },
  { label: 'Allow list', value: 'allowlist' },
  { label: 'All', value: 'all' },
];

export const QUERY_STRING_OPTIONS = [
  { label: 'None', value: 'none' },
  { label: 'Allow list', value: 'allowlist' },
  { label: 'All', value: 'all' },
];

export const CURRENT_COMPRESSION_OPTIONS = [
  { label: 'Manual', value: 'manual' },
  { label: 'Automatic', value: 'automatic' },
];

const formatPromptR1v = `{{ content | trim }}\nA conversation between User and Assistant. The user asks a question, and the Assistant solves it. The assistant first thinks about the reasoning process in the mind and then provides the user with the answer. The reasoning process and answer are enclosed within <think> </think> and <answer> </answer> tags, respectively, i.e., <think> reasoning process here </think><answer> answer here </answer>`

const formatPromptMath = `{{ content | trim }}\nYou FIRST think about the reasoning process as an internal monologue and then provide the final answer. The reasoning process MUST BE enclosed within <think> </think> tags. The final answer MUST BE put in \\boxed{}.`

export const FORMAT_PROMPT_OPTIONS = {math:formatPromptMath,r1v:formatPromptR1v}

export const CODE_EDITOR_THEMES = {
  light: [
    'chrome',
    'cloud_editor',
    'clouds',
    'crimson_editor',
    'dawn',
    'dreamweaver',
    'eclipse',
    'github',
    'iplastic',
    'katzenmilch',
    'kuroir',
    'solarized_light',
    'sqlserver',
    'textmate',
    'tomorrow',
    'xcode',
  ],
  dark: [
    'ambiance',
    'chaos',
    'cloud_editor_dark',
    'clouds_midnight',
    'cobalt',
    'dracula',
    'gob',
    'gruvbox',
    'idle_fingers',
    'kr_theme',
    'merbivore_soft',
    'merbivore',
    'mono_industrial',
    'monokai',
    'nord_dark',
    'pastel_on_dark',
    'solarized_dark',
    'terminal',
    'tomorrow_night_blue',
    'tomorrow_night_bright',
    'tomorrow_night_eighties',
    'tomorrow_night',
    'twilight',
    'vibrant_ink',
  ],
};
